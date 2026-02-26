# services/album_service.py
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
    info.get("artistName")
      or artist_from_list
      or info.get("artist")
      or info.get("subtitle")
    )
    if isinstance(name, str) and " • " in name:
        name = name.split(" • ", 1)[0].strip()
    return name

def build_album_payload(
    album_id: str,
    raw: dict,
    info: dict,
    tracks: list | None = None,
    more_from_artist: list | None = None,
    events: list | None = None,
) -> dict:
    """Pura. Transforma datos crudos en payload final."""
    return {
        "id": album_id,
        "info": info,
        "tracks": tracks or [],
        "otherVersions": parse_album_other_versions(raw) or [],
        "moreFromArtist": more_from_artist or [],
        "upcomingEvents": events or [],
        "releasesForYou": parse_album_releases_for_you(raw) or [],
    }

def get_album_tracks(audio_playlist_id: str) -> list:
    """Trae tracks de un álbum por su audioPlaylistId."""
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
            return {"id": album_id, "error": "not_found"}
        
        info = parse_album_info(raw) or {}

        artist_id = info.get("artistId")
        artist_name = extract_artist_name(info)
        audio_playlist_id = info.get("audioPlaylistId")

        # Fetch tracks y more_from_artist en paralelo
        results = gather({
            "tracks": lambda: get_album_tracks(audio_playlist_id),
            "more_from": lambda: get_more_from_artist(artist_id, exclude_album_id=album_id) if artist_id else [],
        })

        tracks = results["tracks"] or []
        more_from = results["more_from"] or []
        
        events = []
        if artist_name:
            events = get_events_cached_only(artist_name, limit=1)
            if not events:
                schedule_events_refresh(artist_name)

        payload = build_album_payload(album_id, raw, info, tracks=tracks, more_from_artist=more_from, events=events)
        set_cached(CacheType.ALBUM, payload, suffix=album_id)
        return payload
    
    except Exception as e:
        print(f"[album_service][get_album][ERR] {album_id}: {e}")
        return {"id": album_id, "error": str(e)}