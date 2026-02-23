# routes/artists.py
"""
Endpoints de artistas
Extraído de music.py según estructura oficial FastAPI
"""
import time
import concurrent.futures as cf

from fastapi import APIRouter, Query, Path
from fastapi.responses import JSONResponse

from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType
from services.upcoming_releases_repo import get_upcoming_by_artist_id_cached
from services.feed_repo import list_new_releases_for_artist

from utils.artist_parser import (
    parse_top_songs_v2,
    parse_albums,
    parse_singles_eps,
    parse_related_artists,
    pick_related_artists_section,
)
from utils.events_upcoming import fetch_upcoming_events_by_artist

from shared.clients import _ytm, _ytmusic_client
from routes.audio import (
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
    """Si no hay eventos en cache, refrescarlos en background."""
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
# ARTIST PAYLOAD
# ═══════════════════════════════════════════════════════════════════════════════

def _artist_payload(artist_id: str):
    # 0) cliente ytmusicapi
    yt = _ytmusic_client()
    
    # 1) get_artist para top songs v2 y hasMore checks
    artist_data = yt.get_artist(artist_id)
    
    # 2) InnerTube browse para parsers manuales
    yt_inner = _ytm()
    response = yt_inner.browse(artist_id)

    # 3) header + secciones desde browse (parsers legacy)
    header = response.get("header", {}).get("musicImmersiveHeaderRenderer", {})
    name = header.get("title", {}).get("runs", [{}])[0].get("text")
    desc = "".join(run.get("text", "") for run in header.get("description", {}).get("runs", []))
    thumbs = (
        header.get("thumbnail", {})
        .get("musicThumbnailRenderer", {})
        .get("thumbnail", {})
        .get("thumbnails", [])
    )

    contents = (
        response.get("contents", {})
        .get("singleColumnBrowseResultsRenderer", {})
        .get("tabs", [])[0]
        .get("tabRenderer", {})
        .get("content", {})
        .get("sectionListRenderer", {})
        .get("contents", [])
    )

    rel_sec = pick_related_artists_section(contents)

    # 4) Upcoming events
    upcoming_events = []
    try:
        # (a) Intentar cache global por artist_id primero
        if artist_id in _ARTIST_CACHE:
            cached_payload = _ARTIST_CACHE[artist_id].get("payload", {})
            cached_evs = cached_payload.get("upcomingEvents") or []
            if cached_evs:
                upcoming_events = cached_evs[:10]
        
        # (b) Si no, buscar por nombre
        if not upcoming_events and name and name.strip():
            ev_cached = get_cached(CacheType.EVENTS, suffix=name.lower())
            if isinstance(ev_cached, dict):
                upcoming_events = (ev_cached.get("events") or [])[:10]
            else:
                # Agendar refresh async
                _schedule_events_refresh_by_name(name.strip())
    except Exception as _e:
        print(f"[artist][events][WARN] {name}: {_e}")

    # 5) Albums - detectar sección por título
    albums_sec = None
    singles_sec = None

    for sec in contents:
        shelf = sec.get("musicCarouselShelfRenderer")
        if not shelf:
            continue
        title_runs = (shelf.get("header", {}).get("musicCarouselShelfBasicHeaderRenderer", {})
                      .get("title", {}).get("runs", []))
        title = (title_runs[0].get("text", "") if title_runs else "").lower()

        if "album" in title and "single" not in title:  # solo "Albums"
            albums_sec = sec
        elif "single" in title or "ep" in title:  # "Singles & EPs"
            singles_sec = sec

    albums_filtered = (parse_albums(albums_sec) if albums_sec else [])[:10]
    albums_section = artist_data.get("albums", {})
    has_more_albums = albums_section.get("browseId") is not None and len(albums_section.get("results", [])) >= 10

    # 6) Singles
    singles_filtered = (parse_singles_eps(singles_sec) if singles_sec else [])[:10]
    singles_section = artist_data.get("singles", {})
    has_more_singles = singles_section.get("browseId") is not None and len(singles_section.get("results", [])) >= 10

    # 7) payload (SIN upcoming_album)
    payload = {
        "header": {
            "name": name,
            "description": desc,
            "thumbnails": thumbs,
        },
        "topSongs": parse_top_songs_v2(artist_data, _ytmusic_client()),
        "albums": albums_filtered,
        "singles_eps": singles_filtered,
        "has_more": {
            "albums": has_more_albums,
            "singles": has_more_singles
        },
        "related": parse_related_artists(rel_sec) if rel_sec else [],
        "upcomingEvents": upcoming_events,
    }

    # 8) new releases
    try:
        payload["newReleases"] = list_new_releases_for_artist(artist_id, limit=8)
    except Exception as _e:
        print(f"[artist][new_releases][WARN] {artist_id}: {_e}")
        payload["newReleases"] = []

    # 9) cache y warm
    _ARTIST_CACHE[artist_id] = {"ts": time.time(), "payload": payload}
    set_cached(CacheType.ARTIST, payload, suffix=artist_id)
    try:
        ids = [t.get("id") for t in payload["topSongs"] if t.get("id")]
        _schedule_warm(ids[:_WARM_BURST])
    except Exception as _e:
        print(f"[artist][warm][WARN] {_e}")

    if not payload.get("albums"):
        payload.pop("albums", None)
    if not payload.get("singles_eps"):
        payload.pop("singles_eps", None)
    if not payload.get("topSongs"):
        payload.pop("topSongs", None)
            
    return payload


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/artist")
def get_artist_q(id: str = Query(...)):
    # 1) Obtener datos cacheados del artista
    cached = get_cached(CacheType.ARTIST, suffix=id)
    if not cached:
        cached = _artist_payload(id)
    
    # 2) ENRIQUECER upcomingEvents si está vacío (post-cache)
    if not cached.get("upcomingEvents"):
        try:
            artist_name = cached.get("header", {}).get("name")
            if artist_name and artist_name.strip():
                ev_cached = get_cached(CacheType.EVENTS, suffix=artist_name.lower())
                if isinstance(ev_cached, dict) and ev_cached.get("events"):
                    cached["upcomingEvents"] = (ev_cached.get("events") or [])[:10]
        except Exception as _e:
            print(f"[artist][events_enrich][ERR] {id}: {_e}")
    
    # 3) Agregar upcoming_album con caché separado inteligente
    try:
        cached["upcoming_album"] = get_upcoming_by_artist_id_cached(id)
    except Exception as _e:
        print(f"[artist][upcoming_album][ERR] {id}: {_e}")
        cached["upcoming_album"] = None
    
    return cached


@router.get("/artist/{id}")
def get_artist_p(id: str = Path(...)):
    # 1) Obtener datos cacheados del artista
    cached = get_cached(CacheType.ARTIST, suffix=id)
    if not cached:
        cached = _artist_payload(id)
    
    # 2) ENRIQUECER upcomingEvents si está vacío (post-cache)
    if not cached.get("upcomingEvents"):
        try:
            artist_name = cached.get("header", {}).get("name")
            if artist_name and artist_name.strip():
                ev_cached = get_cached(CacheType.EVENTS, suffix=artist_name.lower())
                if isinstance(ev_cached, dict) and ev_cached.get("events"):
                    cached["upcomingEvents"] = (ev_cached.get("events") or [])[:10]
        except Exception as _e:
            print(f"[artist][events_enrich][ERR] {id}: {_e}")
    
    # 3) Agregar upcoming_album con caché separado inteligente
    try:
        cached["upcoming_album"] = get_upcoming_by_artist_id_cached(id)
    except Exception as _e:
        print(f"[artist][upcoming_album][ERR] {id}: {_e}")
        cached["upcoming_album"] = None
    
    return cached


@router.get("/artist/{id}/albums")
def get_artist_all_albums(id: str = Path(...)):
    """Devuelve TODOS los albums del artista"""
    # Chequear caché
    cached = get_cached(CacheType.ARTIST_ALBUMS, suffix=id)
    if cached is not None:
        return cached
    
    try:
        yt = _ytmusic_client()
        artist_data = yt.get_artist(id)
        
        albums_section = artist_data.get("albums", {})
        albums_browse_id = albums_section.get("browseId")
        albums_params = albums_section.get("params")
        
        if albums_browse_id:
            all_albums_raw = yt.get_artist_albums(albums_browse_id, albums_params)
        else:
            all_albums_raw = albums_section.get("results", [])
        
        albums_filtered = []
        for album in all_albums_raw:
            albums_filtered.append({
                "id": album.get("browseId"),
                "title": album.get("title"),
                "year": album.get("year"),
                "thumbnails": album.get("thumbnails", [])
            })
        
        result = {
            "artist_id": id,
            "total": len(albums_filtered),
            "albums": albums_filtered
        }
        
        # Guardar en caché
        set_cached(CacheType.ARTIST_ALBUMS, result, suffix=id)
        return result
        
    except Exception as e:
        import traceback
        return JSONResponse(status_code=500, content={
            "error": str(e),
            "traceback": traceback.format_exc()
        })


@router.get("/artist/{id}/singles")
def get_artist_all_singles(id: str = Path(...)):
    """Devuelve TODOS los singles/EPs del artista"""
    # Chequear caché
    cached = get_cached(CacheType.ARTIST_SINGLES, suffix=id)
    if cached is not None:
        return cached
    
    try:
        yt = _ytmusic_client()
        artist_data = yt.get_artist(id)
        
        singles_section = artist_data.get("singles", {})
        singles_browse_id = singles_section.get("browseId")
        singles_params = singles_section.get("params")
        
        if singles_browse_id:
            all_singles_raw = yt.get_artist_albums(singles_browse_id, singles_params)
        else:
            all_singles_raw = singles_section.get("results", [])
        
        with cf.ThreadPoolExecutor(max_workers=10) as executor:
            def fetch_single_info(single):
                browse_id = single.get("browseId")
                album_info = yt.get_album(browse_id) if browse_id else {}
                
                return {
                    "id": browse_id,
                    "title": single.get("title"),
                    "type": album_info.get("type", single.get("type", "Single")),
                    "year": album_info.get("year"),
                    "thumbnails": single.get("thumbnails", []),
                    "trackCount": album_info.get("trackCount")
                }
            
            singles_filtered = list(executor.map(fetch_single_info, all_singles_raw))
        
        result = {
            "artist_id": id,
            "total": len(singles_filtered),
            "singles": singles_filtered
        }
        
        # Guardar en caché
        set_cached(CacheType.ARTIST_SINGLES, result, suffix=id)
        return result
        
    except Exception as e:
        import traceback
        return JSONResponse(status_code=500, content={
            "error": str(e),
            "traceback": traceback.format_exc()
        })