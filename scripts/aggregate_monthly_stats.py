"""
Agrega estadísticas mensuales desde user_activity a user_monthly_stats.
Corre el día 1 de cada mes a las 03:00 (GitHub Actions).
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Dict, List, Any
import sys
import os

# Agregar el path del proyecto para imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.supabase_service import supabase_service as sb

def get_first_day_of_last_month() -> str:
    """Retorna el primer día del mes pasado en formato YYYY-MM-DD"""
    today = datetime.now()
    first_of_this_month = today.replace(day=1)
    last_month = first_of_this_month - timedelta(days=1)
    first_of_last_month = last_month.replace(day=1)
    return first_of_last_month.strftime('%Y-%m-%d')

def aggregate_for_user(user_id: str, month: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Lee user_activity del mes y retorna top 5-10 por entity_type.

    TODO: Optimización futura - Leer de user_weekly_stats en vez de user_activity
          Consolidar las 4 semanas del mes (más eficiente).
          Requiere: validar que las 4 semanas existan antes de consolidar,
          si falta alguna → fallback a leer user_activity.
    
    Retorna: { 'artist': [...], 'album': [...], 'track': [...] }
    """
    # Calcular primer día del mes siguiente
    month_date = datetime.strptime(month, '%Y-%m-%d')
    next_month = (month_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    month_end = next_month.strftime('%Y-%m-%d')
    
    print(f"  📊 Procesando user {user_id} | mes {month} - {month_end}")
    
    # Leer plays del mes
    response = sb.table('user_activity') \
        .select('entity_type, entity_id, play_count, metadata') \
        .eq('user_id', user_id) \
        .eq('event_type', 'play') \
        .gte('occurred_at', month) \
        .lt('occurred_at', month_end) \
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

def save_monthly_stats(user_id: str, month: str, entity_type: str, stats: List[Dict[str, Any]]):
    """Guarda stats en user_monthly_stats con UPSERT"""
    if not stats:
        print(f"{entity_type}: sin datos, skip")
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
    
    print(f"{entity_type}: {len(stats)} items guardados")

def main():
    print("Iniciando agregación mensual...")
    
    month = get_first_day_of_last_month()
    print(f"Mes: {month}")
    
    # Calcular fin de mes
    month_date = datetime.strptime(month, '%Y-%m-%d')
    next_month = (month_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    month_end = next_month.strftime('%Y-%m-%d')
    
    # Obtener todos los usuarios con actividad en el mes
    response = sb.table('user_activity') \
        .select('user_id') \
        .eq('event_type', 'play') \
        .gte('occurred_at', month) \
        .lt('occurred_at', month_end) \
        .execute()
    
    plays = response.data or []
    user_ids = list(set(play['user_id'] for play in plays))
    
    print(f"Usuarios con actividad: {len(user_ids)}")
    
    for user_id in user_ids:
        stats = aggregate_for_user(user_id, month)
        
        for entity_type, items in stats.items():
            save_monthly_stats(user_id, month, entity_type, items)
    
    print("Agregación mensual completada")

if __name__ == '__main__':
    main()