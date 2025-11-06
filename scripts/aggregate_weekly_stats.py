"""
Agrega estadísticas semanales desde user_activity a user_weekly_stats.
Corre cada domingo a las 23:59 (GitHub Actions).
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Dict, List, Any
import sys
import os

# Agregar el path del proyecto para imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.supabase_service import supabase_service as sb

def get_monday_of_last_week() -> str:
    """Retorna el lunes de la semana pasada en formato YYYY-MM-DD"""
    today = datetime.now()
    # Cuántos días atrás está el lunes pasado
    days_since_monday = today.weekday()  # 0=lunes, 6=domingo
    days_to_last_monday = days_since_monday + 7
    last_monday = today - timedelta(days=days_to_last_monday)
    return last_monday.strftime('%Y-%m-%d')

def aggregate_for_user(user_id: str, week_start: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Lee user_activity de la semana y retorna top 5-10 por entity_type.
    Retorna: { 'artist': [...], 'album': [...], 'track': [...] }
    """
    week_end = (datetime.strptime(week_start, '%Y-%m-%d') + timedelta(days=7)).strftime('%Y-%m-%d')
    
    print(f"Procesando user {user_id} | semana {week_start} - {week_end}")
    
    # Leer plays de la semana
    response = sb.table('user_activity') \
        .select('entity_type, entity_id, play_count, metadata') \
        .eq('user_id', user_id) \
        .eq('event_type', 'play') \
        .gte('occurred_at', week_start) \
        .lt('occurred_at', week_end) \
        .execute()
    
    plays = response.data or []
    
    # Agrupar por entity_type + entity_id
    stats_by_type: Dict[str, Dict[str, Dict[str, Any]]] = {
        'artist': {},
        'album': {},
        'track': {}
    }
    
    for play in plays:
        entity_type = play['entity_type']
        entity_id = play['entity_id']
        play_count = play.get('play_count', 1)
        metadata = play.get('metadata', {})
        
        if entity_type not in stats_by_type:
            continue
        
        if entity_id not in stats_by_type[entity_type]:
            stats_by_type[entity_type][entity_id] = {
                'entity_id': entity_id,
                'play_count': 0,
                'display_name': metadata.get('display_name'),
                'thumbnail_url': metadata.get('thumbnail_url')
            }
        
        stats_by_type[entity_type][entity_id]['play_count'] += play_count
    
    # Ordenar y tomar top 5-10
    result = {}
    for entity_type, items in stats_by_type.items():
        sorted_items = sorted(items.values(), key=lambda x: x['play_count'], reverse=True)
        # Tomar hasta 10, pero mínimo lo que haya
        top_items = sorted_items[:10] if len(sorted_items) >= 5 else sorted_items[:5]
        result[entity_type] = top_items
        print(f"    {entity_type}: {len(top_items)} items (total: {len(sorted_items)})")
    
    return result

def save_weekly_stats(user_id: str, week_start: str, entity_type: str, stats: List[Dict[str, Any]]):
    """Guarda stats en user_weekly_stats con UPSERT"""
    if not stats:
        print(f"{entity_type}: sin datos, skip")
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
    
    print(f"{entity_type}: {len(stats)} items guardados")

def main():
    print("Iniciando agregación semanal...")
    
    week_start = get_monday_of_last_week()
    print(f"Semana: {week_start}")
    
    # Obtener todos los usuarios con actividad en la semana
    week_end = (datetime.strptime(week_start, '%Y-%m-%d') + timedelta(days=7)).strftime('%Y-%m-%d')
    
    response = sb.table('user_activity') \
        .select('user_id') \
        .eq('event_type', 'play') \
        .gte('occurred_at', week_start) \
        .lt('occurred_at', week_end) \
        .execute()
    
    plays = response.data or []
    user_ids = list(set(play['user_id'] for play in plays))
    
    print(f"Usuarios con actividad: {len(user_ids)}")
    
    for user_id in user_ids:
        stats = aggregate_for_user(user_id, week_start)
        
        for entity_type, items in stats.items():
            save_weekly_stats(user_id, week_start, entity_type, items)
    
    print("Agregación semanal completada")

if __name__ == '__main__':
    main()