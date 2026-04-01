"""
Agrega estadísticas semanales desde play_events a user_weekly_stats.
Usa RPC para hacer GROUP BY en Postgres (escalable).
Corre cada domingo a las 23:59 (GitHub Actions).
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Dict, List, Any
import argparse
import re
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.supabase_service import supabase_service as sb
from services.artist_service import get_artist

from services.cache_config import set_manual_version, CacheType
from services.cache_service import invalidate_all

def get_monday_of_last_week() -> str:
    today = datetime.now()
    days_since_monday = today.weekday()
    days_to_last_monday = days_since_monday + 7
    last_monday = today - timedelta(days=days_to_last_monday)
    return last_monday.strftime('%Y-%m-%d')

def aggregate_for_user(user_id: str, week_start: str, week_end: str) -> Dict[str, List[Dict[str, Any]]]:
    print(f"Procesando user {user_id}")
    
    response = sb.rpc('aggregate_user_weekly_stats', {
        'p_user_id': user_id,
        'p_week_start': week_start,
        'p_week_end': week_end
    }).execute()
    
    result = response.data or {'track': [], 'artist': [], 'album': []}
    
    for entity_type in ['track', 'artist', 'album']:
        items = result.get(entity_type, [])
        print(f"    {entity_type}: {len(items)} items")

    return result

def save_weekly_stats(user_id: str, week_start: str, entity_type: str, stats: List[Dict[str, Any]]):
    if not stats:
        return
    
    data = {
        'user_id': user_id,
        'week_start': week_start,
        'entity_type': entity_type,
        'stats': stats
    }
    
    sb.table('user_weekly_stats').upsert(
        data,
        on_conflict='user_id,week_start,entity_type'
    ).execute()
    
    print(f" ✓ {entity_type}: {len(stats)} guardados")

def enrich_artist_thumbnails(artists: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def fetch_thumb(artist):
        artist_id = artist.get('entity_id')
        if not artist_id:
            return
        try:
            data = get_artist(sb, artist_id)
            thumbs = (data.get('header') or {}).get('thumbnails') or []
            if thumbs:
                url = thumbs[-1].get('url', '')
                artist['thumbnail_url'] = re.sub(r'=w\d+-h\d+.*$', '=w512-h512-p-l90-rj', url)
        except Exception as e:
            print(f"    thumb FAIL {artist_id}: {e}")

    with ThreadPoolExecutor(max_workers=3) as executor:
        executor.map(fetch_thumb, artists)

    return artists

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--week-start', type=str, default=None)
    args = parser.parse_args()

    print("Iniciando agregación semanal...")

    week_start = args.week_start or get_monday_of_last_week()
    week_end = (datetime.strptime(week_start, '%Y-%m-%d') + timedelta(days=7)).strftime('%Y-%m-%d')
    print(f"Período: {week_start} → {week_end}")
    
    response = sb.rpc('get_active_users_in_period', {
        'p_start': week_start,
        'p_end': week_end
    }).execute()
    
    user_ids = [row['user_id'] for row in (response.data or [])]
    
    print(f"Usuarios con actividad: {len(user_ids)}")
    
    for user_id in user_ids:
        stats = aggregate_for_user(user_id, week_start, week_end)
        
        for entity_type, items in stats.items():
            if entity_type == 'artist':
                items = enrich_artist_thumbnails(items)
            if entity_type != "track":
                for item in items:
                    item.pop("duration_seconds", None)
            save_weekly_stats(user_id, week_start, entity_type, items)
    
    print("Agregación semanal completada")

    invalidate_all(CacheType.WEEKLY_STATS)
    set_manual_version(CacheType.WEEKLY_STATS)
    print("[cache] WEEKLY_STATS invalidado")

if __name__ == '__main__':
    main()