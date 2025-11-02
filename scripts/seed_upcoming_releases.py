# scripts/seed_upcoming_releases.py
"""
Script para insertar releases de nov/dic 2025 en Supabase.

Uso:
  python scripts/seed_upcoming_releases.py albums_with_covers.json

Opciones:
  --dry-run: Solo muestra qué haría sin insertar
  --clear: Borra todo antes de insertar
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime

# Agregar parent dir al path para imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.supabase_service import supabase_service as sb

TABLE = "upcoming_releases"

def filter_nov_dec_2025(albums: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filtra solo releases de noviembre/diciembre 2025"""
    filtered = []
    for album in albums:
        release_date = album.get("release_date", "")
        
        # Si es TBA, lo incluimos
        if release_date == "TBA":
            filtered.append(album)
            continue
        
        # Si tiene fecha, verificar que sea nov/dic 2025
        if release_date and isinstance(release_date, str):
            if release_date.startswith("2025-11") or release_date.startswith("2025-12"):
                filtered.append(album)
    
    return filtered

def map_to_db_row(album: Dict[str, Any]) -> Dict[str, Any]:
    """Mapea el formato del scraper al schema de la DB"""
    release_date = album.get("release_date")
    
    return {
        "artist_name": album.get("artist"),
        "artist_id": album.get("artist_id"),  # Puede ser None
        "album_name": album.get("album"),
        "release_date": None if release_date == "TBA" else release_date,
        "is_tba": release_date == "TBA",
        "label": album.get("label"),
        "thumbnail_url": album.get("thumbnail"),
        "track_count": album.get("track_count"),
    }

def clear_table():
    """Borra todo el contenido de la tabla"""
    print("⚠️  Borrando contenido existente...")
    try:
        result = sb.table(TABLE).delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        count = getattr(result, "count", None)
        print(f"✅ Borrados: {count if count else 'OK'}")
    except Exception as e:
        print(f"❌ Error borrando: {e}")
        sys.exit(1)

def insert_releases(rows: List[Dict[str, Any]], dry_run: bool = False):
    """Inserta los releases en Supabase"""
    if dry_run:
        print("\n🔍 DRY RUN - No se insertará nada\n")
        for i, row in enumerate(rows[:5], 1):
            print(f"{i}. {row['artist_name']} - {row['album_name']}")
            print(f"   Fecha: {row['release_date'] or 'TBA'}")
            print(f"   Cover: {'✓' if row['thumbnail_url'] else '✗'}")
            print(f"   Artist ID: {'✓' if row['artist_id'] else '✗'}\n")
        
        if len(rows) > 5:
            print(f"... y {len(rows) - 5} más\n")
        
        print(f"Total a insertar: {len(rows)}")
        return
    
    print(f"\n📥 Insertando {len(rows)} releases...")
    
    try:
        # Insertar en batch
        result = sb.table(TABLE).insert(rows).execute()
        inserted_count = len(getattr(result, "data", []))
        
        print(f"✅ Insertados: {inserted_count}")
        
        # Stats
        with_cover = sum(1 for r in rows if r.get("thumbnail_url"))
        with_artist_id = sum(1 for r in rows if r.get("artist_id"))
        tba_count = sum(1 for r in rows if r.get("is_tba"))
        
        print(f"\n📊 Estadísticas:")
        print(f"   Con cover: {with_cover}/{len(rows)}")
        print(f"   Con artist_id: {with_artist_id}/{len(rows)}")
        print(f"   TBA: {tba_count}")
        
    except Exception as e:
        print(f"❌ Error insertando: {e}")
        sys.exit(1)

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Seed upcoming releases en Supabase")
    parser.add_argument("json_file", help="Archivo JSON con los álbumes")
    parser.add_argument("--dry-run", action="store_true", help="No insertar, solo mostrar")
    parser.add_argument("--clear", action="store_true", help="Borrar todo antes de insertar")
    
    args = parser.parse_args()
    
    # Leer JSON
    json_path = Path(args.json_file)
    if not json_path.exists():
        print(f"❌ No existe el archivo: {json_path}")
        sys.exit(1)
    
    print(f"📖 Leyendo {json_path}...")
    with open(json_path, "r", encoding="utf-8") as f:
        albums = json.load(f)
    
    print(f"✅ Cargados {len(albums)} álbumes del JSON")
    
    # Filtrar nov/dic 2025
    filtered = filter_nov_dec_2025(albums)
    print(f"🎯 Filtrados nov/dic 2025: {len(filtered)} álbumes")
    
    if len(filtered) == 0:
        print("⚠️  No hay álbumes para insertar")
        sys.exit(0)
    
    # Mapear a formato DB
    rows = [map_to_db_row(album) for album in filtered]
    
    # Validar que tengan lo mínimo
    valid_rows = [r for r in rows if r.get("artist_name") and r.get("album_name")]
    if len(valid_rows) < len(rows):
        print(f"⚠️  Descartados {len(rows) - len(valid_rows)} álbumes sin artist/album")
    
    # Borrar si se pidió
    if args.clear and not args.dry_run:
        clear_table()
    
    # Insertar
    insert_releases(valid_rows, dry_run=args.dry_run)
    
    print("\n✨ Listo!")

if __name__ == "__main__":
    main()