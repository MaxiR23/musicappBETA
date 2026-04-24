"""
Test: simula el POST /playlists/{id}/tracks con el shape nuevo de body.
Valida que el backend acepta artists array y que todo se guarda bien.
"""
from __future__ import annotations
import uuid

from services.supabase_service import supabase_service as sb
from services.playlist_service import add_track, create_playlist, delete_playlist


def main() -> int:
    user_id = input("Pegá tu user_id (UUID de auth.users): ").strip()
    if not user_id:
        print("user_id requerido")
        return 1

    print("\n1. Creando playlist de test...")
    playlist = create_playlist(
        db=sb,
        user_id=user_id,
        title=f"Test playlist {uuid.uuid4().hex[:6]}",
        description="Test del refactor",
        is_public=False,
    )
    playlist_id = playlist["id"]
    print(f"   Playlist creada: {playlist_id}")

    print("\n2. Simulando body del frontend con shape nuevo...")
    body = {
        "track_id": "jPe0bX_GtBo",
        "title": "INDUSTRY BABY",
        "artists": [
            {"id": "UCCF_6PwrZf1u70yghKms3Mw", "name": "Lil Nas X"},
            {"id": "UCKIOM0Wi1qNV8HFLArK-uYQ", "name": "Jack Harlow"},
        ],
        "album": "INDUSTRY BABY",
        "album_id": "MPREb_Qc7Ug37UWyt",
        "duration_seconds": 212,
        "thumbnail_url": "https://lh3.googleusercontent.com/1zJQeKEbH6zGFD_SnFiiMBrWvDNaCx_tNbH4AbgyjtKffdrd-sAHqyaMHmj1WTApvKyFupA5mJ192u_T=w120-h120-l90-rj",
    }

    print("\n3. Llamando add_track...")
    try:
        result = add_track(
            db=sb,
            service_db=sb,
            user_id=user_id,
            playlist_id=playlist_id,
            track_id=body["track_id"],
            body=body,
        )
        print("   Insertado OK")
        print(f"   Track: {result['track']}")
        print(f"   Link:  {result['link']}")
    except Exception as e:
        print(f"   ERROR: {e}")
        print("\n   Limpiando playlist de test...")
        delete_playlist(db=sb, user_id=user_id, playlist_id=playlist_id)
        return 1

    print(f"\n4. Verificá en Supabase:")
    print(f"   - tracks (track_id = 'jPe0bX_GtBo')")
    print(f"   - playlist_tracks (playlist_id = '{playlist_id}')")
    print(f"\n   Cuando termines, borrá la playlist de test corriendo:")
    print(f"   DELETE FROM playlists WHERE id = '{playlist_id}';")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())