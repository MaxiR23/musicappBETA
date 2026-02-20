# routes/search.py
"""
Endpoint de búsqueda
Extraído de music.py según estructura oficial FastAPI
"""
from fastapi import APIRouter, Query, Request

from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType

from utils.search_parser import (
    parse_artist_card_info,
    parse_artist_card_songs,
    parse_artist_card_albums,
    parse_search_albums_and_songs,
)

from shared.clients import _ytm, _ytmusic_client
from routes.audio import _schedule_warm

router = APIRouter()
# ═══════════════════════════════════════════════════════════════════════════════
# SEARCH
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/search")
def search_music(request: Request, q: str = Query(..., description="Texto a buscar")):
    cached = get_cached(CacheType.SEARCH, suffix=q.lower()[:100])
    if cached:
        try:
            artist_ids = [s.get("videoId") for s in (cached.get("artistSongs") or []) if s.get("videoId")]
            general_ids = [] if cached.get("artist") else [s.get("videoId") for s in (cached.get("search", {}).get("songs") or []) if s.get("videoId")]
            _schedule_warm(list(dict.fromkeys(artist_ids + general_ids))[:24])
        except Exception as _e:
            print(f"[search][cached][warm][WARN] {_e}")
        return cached

    yt = _ytm()
    yt_api = _ytmusic_client()
    response = yt.search(q)

    artist        = parse_artist_card_info(response)
    artist_songs  = parse_artist_card_songs(response, strict_atv=True, yt_innertube=yt, yt_api=yt_api, enrich_metadata=True)
    artist_albums = parse_artist_card_albums(response)

    if artist:
        general = parse_search_albums_and_songs(response, song_limit=0, album_limit=10)
    else:
        general = parse_search_albums_and_songs(response, song_limit=10, album_limit=10, yt_innertube=yt, yt_api=yt_api, enrich_metadata=True)

    result = {
        "query": q,
        "artist": artist,
        "artistSongs": artist_songs,
        "artistAlbums": artist_albums,
        "search": general,
    }
    set_cached(CacheType.SEARCH, result, suffix=q.lower()[:100])

    try:
        artist_ids = [s.get("videoId") for s in (artist_songs or []) if s.get("videoId")]
        general_ids = [] if artist else [s.get("videoId") for s in (general.get("songs") or []) if s.get("videoId")]
        _schedule_warm(list(dict.fromkeys(artist_ids + general_ids))[:24])
    except Exception as _e:
        print(f"[search][warm][WARN] {type(_e).__name__}: {_e}")

    return result