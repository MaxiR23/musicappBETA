"""
Lógica de albums.
Funciones puras para builds, orquestación para fetches.
"""
from services import music_client
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType
from services.events_service import get_events_cached_only, schedule_events_refresh
from services.artist_service import get_more_from_artist
from services.executor import gather
from utils.album_parser import (
    parse_album_info,
    parse_album_other_versions,
    parse_album_releases_for_you,
    parse_tracks_from_audio_playlist,
)

def extract_artist_name(info: dict) -> str | None:
    """Extrae nombre del artista desde album info."""
    artists = info.get("artists") or []
    first = artists[0] if isinstance(artists, list) and artists else {}
    artist_from_list = first.get("name") if isinstance(first, dict) else None
    name = (
        info.get("artist_name")
        or artist_from_list
        or info.get("artist")
        or info.get("subtitle")
    )
    if isinstance(name, str) and " • " in name:
        name = name.split(" • ", 1)[0].strip()
    return name

def enrich_album_tracks(tracks: list[dict] | None, album_id: str, info: dict | None = None) -> list[dict]:
    """Agrega contexto de álbum a cada track."""
    if not tracks:
        return []
    info = info or {}
    album_name = info.get("title")
    return [{**track, "album_id": album_id, "album_name": album_name} for track in tracks]

def build_album_payload(
    album_id: str,
    raw: dict,
    info: dict,
    tracks: list | None = None,
    more_from_artist: list | None = None,
    events: list | None = None,
) -> dict:
    """Transforma datos crudos en payload final."""
    return {
        "id": album_id,
        "info": info,
        "tracks": tracks or [],
        "other_versions": parse_album_other_versions(raw) or [],
        "more_from_artist": more_from_artist or [],
        "upcoming_events": events or [],
        "releases_for_you": parse_album_releases_for_you(raw) or [],
    }

def build_error_payload(album_id: str, error: str = "service_unavailable") -> dict:
    return {"id": album_id, "error": error}

def should_cache_album(info: dict, tracks: list) -> bool:
    """Decide si el album es válido para cachear."""
    return bool(info.get("title") and tracks)

def get_album_tracks(audio_playlist_id: str) -> list:
    """Trae tracks de un álbum por su audio_playlist_id."""
    if not audio_playlist_id:
        return []
    return parse_tracks_from_audio_playlist(audio_playlist_id)

def get_album(album_id: str, use_cache: bool = True) -> dict:
    """Orquesta: cache -> fetch -> build -> cache."""
    if use_cache:
        cached = get_cached(CacheType.ALBUM, suffix=album_id)
        if cached:
            return cached
    try:
        raw = music_client.browse(album_id)
        if not raw:
            return build_error_payload(album_id, "fetch_failed")

        info = parse_album_info(raw) or {}
        if not info.get("title"):
            print(f"[album_service][WARN] {album_id}: info vacía")
            return build_error_payload(album_id)

        artist_id = info.get("artist_id")
        artist_name = extract_artist_name(info)
        audio_playlist_id = info.get("audio_playlist_id")

        results = gather({
            "tracks": lambda: get_album_tracks(audio_playlist_id),
            "more_from": lambda: get_more_from_artist(artist_id, exclude_album_id=album_id) if artist_id else [],
        })

        tracks = enrich_album_tracks(results["tracks"], album_id=album_id, info=info)
        more_from = results["more_from"] or []

        events = []
        if artist_name:
            events = get_events_cached_only(artist_name, limit=1)
            if not events:
                schedule_events_refresh(artist_name)

        payload = build_album_payload(album_id, raw, info, tracks=tracks, more_from_artist=more_from, events=events)

        if should_cache_album(info, tracks):
            set_cached(CacheType.ALBUM, payload, suffix=album_id)
        else:
            print(f"[album_service][WARN] {album_id}: sin tracks, no se cachea")

        return payload
    except Exception as e:
        print(f"[album_service][ERR] {album_id}: {e}")
        return build_error_payload(album_id)