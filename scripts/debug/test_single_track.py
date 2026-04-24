"""
Test: mapea e inserta un solo track en la tabla tracks.
Sirve para validar que el schema nuevo (artists jsonb) acepta bien el insert.
"""
from __future__ import annotations

from services.supabase_service import supabase_service as sb
from services.genre_repo import upsert_track
from utils.feed_utils import map_track

def main() -> int:
    artist = "Lil Nas X"
    title = "Industry Baby"

    print("=" * 70)
    print(f"Mapeando: {artist} - {title}")
    print("=" * 70)

    track = map_track(artist, title)
    if not track:
        print("No se pudo mapear el track")
        return 1

    print("\nTrack mapeado:")
    for k, v in track.items():
        print(f"  {k}: {v}")

    print("\nInsertando en tracks...")
    try:
        upsert_track(db=sb, track=track)
        print("Insertado correctamente")
    except Exception as e:
        print(f"Error insertando: {e}")
        return 1

    return 0

if __name__ == "__main__":
    raise SystemExit(main())