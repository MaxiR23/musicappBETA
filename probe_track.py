# INFO: Throwaway probe to verify the full track blob has every field TrackPublic needs.
import json
from shared.clients import _ytmusic_client
from services.track_service import normalize_track_item, ensure_artists

VIDEO_ID = "Uew_w8KI4NA"  # Young Miko + Rauw

yt = _ytmusic_client()
wp = yt.get_watch_playlist(videoId=VIDEO_ID) or {}
tracks = wp.get("tracks") or []

if not tracks:
    print("NO TRACKS")
    raise SystemExit

seed = tracks[0]

# 1. Mapper real que ya usas en el backend
normalized = normalize_track_item(seed)

# 2. Resolver ids de colab via album
normalized["artists"] = ensure_artists(normalized.get("artists"), album_id=normalized.get("album_id"))

print("BLOB NORMALIZADO COMPLETO:")
print(json.dumps(normalized, indent=2, ensure_ascii=False))
print("=" * 50)

# 3. Chequeo campo por campo de lo que TrackPublic necesita
print("CHEQUEO TrackPublic:")
print("  id:           ", normalized.get("id"))
print("  title:        ", normalized.get("title"))
print("  artists:      ", normalized.get("artists"))
print("  thumbnail:    ", normalized.get("thumbnail"))
print("  duration_seconds:", normalized.get("duration_seconds"))
print("  album_id:     ", normalized.get("album_id"))
print("  album_name:   ", normalized.get("album_name"))