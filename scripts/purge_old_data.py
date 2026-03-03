"""
Purga datos antiguos de play_events y user_weekly_stats.
Corre cada semana (GitHub Actions).
"""
from __future__ import annotations
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.supabase_service import supabase_service as sb

def purge_play_events(days: int = 60):
    """Borra registros de play_events más antiguos que X días"""
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    print(f"Purgando play_events...")
    print(f"Fecha de corte: {cutoff_date} (hace {days} días)")
    
    try:
        # Contar cuántos se van a borrar
        count_response = sb.table('play_events') \
            .select('id', count='exact') \
            .lt('played_at', cutoff_date) \
            .execute()
        
        count = count_response.count if hasattr(count_response, 'count') else 0
        
        if count == 0:
            print("No hay registros para purgar")
            return
        
        print(f"Se borrarán {count} registros...")
        
        # Borrar
        sb.table('play_events') \
            .delete() \
            .lt('played_at', cutoff_date) \
            .execute()
        
        print(f"✓ {count} registros borrados")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        raise

def purge_weekly_stats(days: int = 90):
    """Borra registros de user_weekly_stats más antiguos que X días"""
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    print(f"\nPurgando user_weekly_stats...")
    print(f"Fecha de corte: {cutoff_date} (hace {days} días)")
    
    try:
        # Contar cuántos se van a borrar
        count_response = sb.table('user_weekly_stats') \
            .select('id', count='exact') \
            .lt('week_start', cutoff_date) \
            .execute()
        
        count = count_response.count if hasattr(count_response, 'count') else 0
        
        if count == 0:
            print("No hay registros para purgar")
            return
        
        print(f"Se borrarán {count} registros...")
        
        # Borrar
        sb.table('user_weekly_stats') \
            .delete() \
            .lt('week_start', cutoff_date) \
            .execute()
        
        print(f"✓ {count} registros borrados")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        raise

def main():
    print("Iniciando purga automática...")
    print(f"Fecha actual: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Purgar play_events (>60 días)
    purge_play_events(days=60)
    
    # Purgar user_weekly_stats (>90 días)
    purge_weekly_stats(days=90)
    
    print("\nPurga completada")

if __name__ == '__main__':
    main()