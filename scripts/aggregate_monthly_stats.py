"""
Agrega estadísticas mensuales desde user_weekly_stats a user_monthly_stats.
Consolida las semanas del mes anterior.
Corre el día 1 de cada mes a las 03:00 (GitHub Actions).
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Dict, List, Any
from collections import defaultdict
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.supabase_service import supabase_service as sb

def get_first_day_of_last_month() -> str:
    """Retorna el primer día del mes pasado en formato YYYY-MM-DD"""
    today = datetime.now()
    first_of_this_month = today.replace(day=1)
    last_month = first_of_this_month - timedelta(days=1)
    first_of_last_month = last_month.replace(day=1)
    return first_of_last_month.strftime('%Y-%m-%d')

def get_month_end(month: str) -> str:
    """Retorna el primer día del mes siguiente"""
    month_date = datetime.strptime(month, '%Y-%m-%d')
    next_month = (month_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    return next_month.strftime('%Y-%m-%d')

def get_weeks_in_month(month: str) -> List[str]:
    """
    Retorna las fechas de inicio de semana (lunes) que caen dentro del mes.
    """
    month_date = datetime.strptime(month, '%Y-%m-%d')
    month_end = datetime.strptime(get_month_end(month), '%Y-%m-%d')
    
    weeks = []
    current = month_date
    
    # Ir al primer lunes del mes (o antes si el mes empieza en lunes)
    while current.weekday() != 0:
        current -= timedelta(days=1)
    
    # Si retrocedimos al mes anterior, avanzar una semana
    if current.month != month_date.month:
        current += timedelta(days=7)
    
    # Recolectar todos los lunes dentro del mes
    while current < month_end:
        if current.month == month_date.month:
            weeks.append(current.strftime('%Y-%m-%d'))
        current += timedelta(days=7)
    
    return weeks

def aggregate_for_user(user_id: str, weeks: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Lee user_weekly_stats de las semanas del mes y consolida.
    Solo lee ~12-15 filas por usuario (4-5 semanas × 3 tipos).
    
    Retorna: { 'artist': [...], 'album': [...], 'track': [...] }
    """
    print(f"Procesando user {user_id}")
    
    # Leer stats de todas las semanas del mes
    response = sb.table('user_weekly_stats') \
        .select('entity_type, stats') \
        .eq('user_id', user_id) \
        .in_('week_start', weeks) \
        .execute()
    
    weekly_data = response.data or []
    
    if not weekly_data:
        print(f"    Sin datos semanales")
        return {'artist': [], 'album': [], 'track': []}
    
    # Consolidar por entity_type
    consolidated: Dict[str, Dict[str, Dict[str, Any]]] = {
        'track': defaultdict(lambda: {'play_count': 0}),
        'artist': defaultdict(lambda: {'play_count': 0}),
        'album': defaultdict(lambda: {'play_count': 0})
    }
    
    for row in weekly_data:
        entity_type = row['entity_type']
        stats = row.get('stats') or []
        
        if entity_type not in consolidated:
            continue
        
        for item in stats:
            entity_id = item.get('entity_id')
            if not entity_id:
                continue
            
            # Sumar play_count
            consolidated[entity_type][entity_id]['play_count'] += item.get('play_count', 0)
            
            # Copiar metadata
            consolidated[entity_type][entity_id]['entity_id'] = entity_id
            consolidated[entity_type][entity_id]['display_name'] = item.get('display_name')
            consolidated[entity_type][entity_id]['thumbnail_url'] = item.get('thumbnail_url')
            
            # Metadata extra según tipo
            if entity_type == 'track':
                consolidated[entity_type][entity_id]['artist_id'] = item.get('artist_id')
                consolidated[entity_type][entity_id]['artist_name'] = item.get('artist_name')
                consolidated[entity_type][entity_id]['album_id'] = item.get('album_id')
                consolidated[entity_type][entity_id]['album_name'] = item.get('album_name')
            elif entity_type == 'album':
                consolidated[entity_type][entity_id]['artist_id'] = item.get('artist_id')
                consolidated[entity_type][entity_id]['artist_name'] = item.get('artist_name')
    
    def top_10(items: Dict) -> List[Dict]:
        sorted_items = sorted(items.values(), key=lambda x: x['play_count'], reverse=True)
        return sorted_items[:10]
    
    result = {
        'track': top_10(consolidated['track']),
        'artist': top_10(consolidated['artist']),
        'album': top_10(consolidated['album'])
    }
    
    for entity_type, items in result.items():
        print(f"    {entity_type}: {len(items)} items")
    
    return result

def save_monthly_stats(user_id: str, month: str, entity_type: str, stats: List[Dict[str, Any]]):
    """Guarda stats en user_monthly_stats con UPSERT"""
    if not stats:
        return
    
    data = {
        'user_id': user_id,
        'month': month,
        'entity_type': entity_type,
        'stats': stats
    }
    
    sb.table('user_monthly_stats').upsert(
        data,
        on_conflict='user_id,month,entity_type'
    ).execute()
    
    print(f"    ✓ {entity_type}: {len(stats)} guardados")


def main():
    print("Iniciando agregación mensual...")
    
    month = get_first_day_of_last_month()
    month_end = get_month_end(month)
    weeks = get_weeks_in_month(month)
    
    print(f"Período: {month} → {month_end}")
    print(f"Semanas: {weeks}")
    
    if not weeks:
        print("No hay semanas para procesar")
        return
    
    # Obtener usuarios con datos en esas semanas (DISTINCT en Postgres)
    response = sb.rpc('get_users_with_weekly_stats', {
        'p_weeks': weeks
    }).execute()
    
    user_ids = [row['user_id'] for row in (response.data or [])]
    
    print(f"Usuarios con actividad: {len(user_ids)}")
    
    for user_id in user_ids:
        stats = aggregate_for_user(user_id, weeks)
        
        for entity_type, items in stats.items():
            save_monthly_stats(user_id, month, entity_type, items)
    
    print("Agregación mensual completada")

if __name__ == '__main__':
    main()