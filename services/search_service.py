# services/search_service.py
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

def build_search_payload(
    query: str,
    artist: dict | None,
    artist_songs: list,
    artist_albums: list,
    general: dict,
) -> dict:
    """Pura. Construye el payload final de búsqueda."""
    return {
        "query": query,
        "artist": artist,
        "artist_songs": artist_songs,
        "artist_albums": artist_albums,
        "search": general,
    }

def get_warm_ids(result: dict) -> list[str]:
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

def search(query: str, use_cache: bool = True) -> dict:
    """Orquesta: cache -> fetch -> parse -> cache."""
    cache_key = query.lower()[:100]
    
    if use_cache:
        cached = get_cached(CacheType.SEARCH, suffix=cache_key)
        if cached:
            return cached

    try:
        yt = _ytm()
        yt_api = _ytmusic_client()
        response = yt.search(query)

        artist = parse_artist_card_info(response)
        artist_songs = parse_artist_card_songs(
            response, 
            strict_atv=True, 
            yt_innertube=yt, 
            yt_api=yt_api, 
            enrich_metadata=True
        )
        artist_albums = parse_artist_card_albums(response)

        if artist:
            general = parse_search_albums_and_songs(
                response, song_limit=0, album_limit=10
            )
        else:
            general = parse_search_albums_and_songs(
                response, 
                song_limit=10, 
                album_limit=10, 
                yt_innertube=yt, 
                yt_api=yt_api, 
                enrich_metadata=True
            )

        result = build_search_payload(query, artist, artist_songs, artist_albums, general)
        set_cached(CacheType.SEARCH, result, suffix=cache_key)
        return result
    
    except Exception as e:
        print(f"[search_service][search][ERR] {query}: {e}")
        return {"query": query, "error": str(e)}