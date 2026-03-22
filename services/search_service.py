"""
Lógica de negocio para búsquedas.
Funciones puras para builds, orquestación para fetches.
"""
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType
from shared.clients import _ytm, _ytmusic_client
from utils.search_parser import (
    parse_artist_card_info,
    parse_artist_card_songs,
    parse_artist_card_albums,
    parse_search_albums_and_songs,
)

def build_cache_key(query: str) -> str:
    return query.lower()[:100]

def build_search_payload(query: str, artist: dict | None, artist_songs: list, artist_albums: list, general: dict) -> dict:
    """Construye el payload final de búsqueda."""
    return {
        "query": query,
        "artist": artist,
        "artist_songs": artist_songs,
        "artist_albums": artist_albums,
        "search": general,
    }

def build_error_payload(query: str, error: str = "service_unavailable") -> dict:
    return {"query": query, "error": error}

def has_valid_data(result: dict) -> bool:
    """Verifica si el resultado tiene datos útiles."""
    return bool(
        result.get("artist")
        or result.get("artist_songs")
        or result.get("artist_albums")
        or (result.get("search") or {}).get("songs")
        or (result.get("search") or {}).get("albums")
    )

def get_warm_ids(result: dict) -> list:
    """Extrae video_ids para warming."""
    artist_ids = [
        s.get("video_id")
        for s in (result.get("artist_songs") or [])
        if s.get("video_id")
    ]
    general_ids = []
    if not result.get("artist"):
        general_ids = [
            s.get("video_id")
            for s in (result.get("search", {}).get("songs") or [])
            if s.get("video_id")
        ]
    return list(dict.fromkeys(artist_ids + general_ids))[:24]

# ── IO ───────────────────────────────────────────────────
def search(query: str, use_cache: bool = True) -> dict:
    cache_key = build_cache_key(query)

    if use_cache:
        cached = get_cached(CacheType.SEARCH, suffix=cache_key)
        if cached:
            return cached

    try:
        yt = _ytm()
        yt_api = _ytmusic_client()
        response = yt.search(query)

        if not response:
            print(f"[search_service][WARN] {query}: respuesta vacía")
            return build_error_payload(query)

        artist = parse_artist_card_info(response)
        artist_songs = parse_artist_card_songs(
            response,
            strict_atv=True,
            yt_innertube=yt,
            yt_api=yt_api,
            enrich_metadata=True
        )
        artist_albums = parse_artist_card_albums(response)

        general = {"songs": [], "albums": []}

        if artist:
            if len(artist_songs) < 5:
                general = parse_search_albums_and_songs(
                    response,
                    song_limit=10 - len(artist_songs),
                    album_limit=10,
                    yt_innertube=yt,
                    yt_api=yt_api,
                    enrich_metadata=True
                )
            else:
                general = parse_search_albums_and_songs(response, song_limit=0, album_limit=10)
        else:
            general = parse_search_albums_and_songs(
                response,
                song_limit=10,
                album_limit=10,
                yt_innertube=yt,
                yt_api=yt_api,
                enrich_metadata=True
            )

        if artist:
            artist_name_lower = (artist.get("name") or "").strip().lower()
            if artist_name_lower:
                def _is_by_artist(song):
                    for a in song.get("artists", []):
                        if (a.get("name") or "").strip().lower() == artist_name_lower:
                            return True
                    return False

                if general.get("songs"):
                    general["songs"] = [s for s in general["songs"] if _is_by_artist(s)]
                artist_songs = [s for s in artist_songs if _is_by_artist(s)]

        result = build_search_payload(query, artist, artist_songs, artist_albums, general)

        if not has_valid_data(result):
            print(f"[search_service][WARN] {query}: resultado vacío")
            return build_error_payload(query)

        set_cached(CacheType.SEARCH, result, suffix=cache_key)
        return result

    except Exception as e:
        print(f"[search_service][ERR] {query}: {e}")
        return build_error_payload(query)