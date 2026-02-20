# routes/albums.py
"""
Endpoints de albums
"""
from fastapi import APIRouter, Query, Path
from fastapi.responses import JSONResponse
import concurrent.futures as cf

from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType

from utils.album_parser import (
    parse_album_info,
    parse_album_other_versions,
    parse_album_releases_for_you,
    parse_tracks_from_audio_playlist,
    build_more_from_artist,
)
from utils.events_upcoming import fetch_upcoming_events_by_artist

from shared.clients import _ytm
from routes.audio import (
    _BACKGROUND_EXECUTOR,
    _ARTIST_CACHE,
    _schedule_warm,
    _WARM_BURST,
    _get_warm_executor,
)

router = APIRouter()
# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _schedule_events_refresh_by_name(artist_name: str):
    """Si no hay eventos en cache, refrescarlos en background sin bloquear /album."""
    if not artist_name:
        return
    def _bg():
        try:
            ev = fetch_upcoming_events_by_artist(artist_name.strip(), limit=1, headliner_only=False)
            set_cached(CacheType.EVENTS, ev, suffix=artist_name.lower())
            aid = (ev or {}).get("attractionId")
            if aid:
                set_cached(CacheType.EVENTS, ev, suffix=f"aid:{aid}")
        except Exception:
            pass
    try:
        _get_warm_executor().submit(_bg)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# ALBUM PAYLOAD
# ═══════════════════════════════════════════════════════════════════════════════

def _album_payload(album_id: str):
    # 0) usar cliente global (evita latencia de nueva sesión)
    yt = _ytm()  # InnerTube("WEB_REMIX") → _ytm() global reuse

    # 1) browse una sola vez
    response = yt.browse(album_id)

    # 2) parsers rápidos del mismo response
    info = parse_album_info(response)
    other_versions   = parse_album_other_versions(response) or []
    releases_for_you = parse_album_releases_for_you(response) or []

    artist_id = (info or {}).get("artistId")

    # 3) UPCOMING EVENTS: usar SOLO cache inmediata; si no hay, agendar refresh en background
    upcoming_events_one = []
    try:
        artist_name = (
            (info or {}).get("artistName")
            or ((info or {}).get("artists") or [{}])[0].get("name")
            or (info or {}).get("artist")
            or (info or {}).get("subtitle")
        )
        if isinstance(artist_name, str) and " • " in artist_name:
            artist_name = artist_name.split(" • ", 1)[0].strip()

        # (a) si ya abriste el artista, reusá cache local en memoria
        if artist_id and artist_id in _ARTIST_CACHE:
            evs_from_artist = (_ARTIST_CACHE[artist_id]["payload"].get("upcomingEvents") or [])
            if evs_from_artist:
                upcoming_events_one = evs_from_artist[:1]

        # (b) cache por nombre
        if not upcoming_events_one and artist_name:
            ev_cached = get_cached(CacheType.EVENTS, suffix=artist_name.lower())
            if isinstance(ev_cached, dict):
                upcoming_events_one = (ev_cached.get("events") or [])[:1]
            else:
                # no bloqueamos: lo resolvemos async
                _schedule_events_refresh_by_name(artist_name)
    except Exception as _e:
        print(f"[album][events][ERR] {album_id}: {_e}")

    # 4) TRACKS + MORE_FROM_ARTIST en paralelo (reduce wall-time)
    apid = (info or {}).get("audioPlaylistId")
    if not apid:
        print("[album][WARN] sin audioPlaylistId → tracks=[]")
        payload = {
            "id": album_id,
            "info": info,
            "tracks": [],
            "otherVersions": other_versions,
            "moreFromArtist": [],
            "upcomingEvents": upcoming_events_one,
            "releasesForYou": releases_for_you,
        }
        set_cached(CacheType.ALBUM, payload, suffix=album_id)
        return payload

    # Futures
    fut_tracks = _BACKGROUND_EXECUTOR.submit(parse_tracks_from_audio_playlist, apid)
    fut_mfa    = _BACKGROUND_EXECUTOR.submit(
        build_more_from_artist, artist_id, album_id, 10
    ) if artist_id else None

    tracks = []
    more_from_artist = []
    try:
        tracks = fut_tracks.result(timeout=2.5)  # corta latencia en fríos/lentos
    except cf.TimeoutError:
        print(f"[album][tracks][TIMEOUT] {album_id}; devolviendo sin bloquear")
        tracks = []
    except Exception as _e:
        print(f"[album][tracks][ERR] {album_id}: {_e}")
        tracks = []

    if fut_mfa:
        try:
            more_from_artist = fut_mfa.result(timeout=1.5)
        except cf.TimeoutError:
            print(f"[album][mfa][TIMEOUT] {album_id}")
            more_from_artist = []
        except Exception as _e:
            print(f"[album][mfa][ERR] {album_id}: {_e}")
            more_from_artist = []

    # 5) calentar IDs (si hay)
    try:
        ids = [t.get("videoId") for t in tracks if isinstance(t, dict) and t.get("videoId")]
        _schedule_warm(ids[:_WARM_BURST])
    except Exception as _e:
        print(f"[album][warm][WARN] {_e}")

    payload = {
        "id": album_id,
        "info": info,
        "tracks": tracks,
        "otherVersions": other_versions,
        "moreFromArtist": more_from_artist,
        "upcomingEvents": upcoming_events_one,
        "releasesForYou": releases_for_you,
    }
    set_cached(CacheType.ALBUM, payload, suffix=album_id)
    return payload

# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════
@router.get("/album")
def get_album_q(id: str = Query(...)):
    cached = get_cached(CacheType.ALBUM, suffix=id)
    if cached:
        return cached
    return _album_payload(id)

@router.get("/album/{id}")
def get_album_p(id: str = Path(...)):
    cached = get_cached(CacheType.ALBUM, suffix=id)
    if cached:
        return cached
    return _album_payload(id)