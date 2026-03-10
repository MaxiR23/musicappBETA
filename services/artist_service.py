# services/artist_service.py
"""
Lógica de negocio para artistas.
Funciones puras para builds, orquestación para fetches.
"""
from services import music_client
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType
from services.executor import gather
from utils.artist_parser import (
    parse_top_songs_v2,
    parse_albums,
    parse_singles_eps,
    parse_related_artists,
    pick_related_artists_section,
)

from shared.clients import _ytmusic_client

from services.events_service import get_events_cached_only, schedule_events_refresh
from services.feed_repo import list_new_releases_for_artist

def parse_header(raw: dict) -> dict:
    """Extrae header del artista desde browse response."""
    header = raw.get("header", {}).get("musicImmersiveHeaderRenderer", {})
    title_runs = header.get("title", {}).get("runs") or []
    name = title_runs[0].get("text") if title_runs else None
    desc_runs = (header.get("description") or {}).get("runs") or []
    desc = "".join(run.get("text", "") for run in desc_runs)
    thumbs = (
        header.get("thumbnail", {})
        .get("musicThumbnailRenderer", {})
        .get("thumbnail", {})
        .get("thumbnails", [])
    )
    return {"name": name, "description": desc, "thumbnails": thumbs}

def parse_contents(raw: dict) -> list:
    tabs = raw.get("contents", {}).get("singleColumnBrowseResultsRenderer", {}).get("tabs") or []
    first_tab = tabs[0] if tabs else {}
    return (
        first_tab
        .get("tabRenderer", {})
        .get("content", {})
        .get("sectionListRenderer", {})
        .get("contents", [])
    )

def find_albums_section(contents: list) -> dict | None:
    """Busca la sección de albums en contents."""
    for sec in contents:
        shelf = sec.get("musicCarouselShelfRenderer")
        if not shelf:
            continue
        title_runs = (
            shelf.get("header", {})
            .get("musicCarouselShelfBasicHeaderRenderer", {})
            .get("title", {})
            .get("runs", [])
        )
        title = (title_runs[0].get("text", "") if title_runs else "").lower()
        if "album" in title and "single" not in title:
            return sec
    return None

def find_singles_section(contents: list) -> dict | None:
    """Busca la sección de singles/EPs en contents."""
    for sec in contents:
        shelf = sec.get("musicCarouselShelfRenderer")
        if not shelf:
            continue
        title_runs = (
            shelf.get("header", {})
            .get("musicCarouselShelfBasicHeaderRenderer", {})
            .get("title", {})
            .get("runs", [])
        )
        title = (title_runs[0].get("text", "") if title_runs else "").lower()
        if "single" in title or "ep" in title:
            return sec
    return None

def get_top_songs(artist_id: str) -> list:
    """Trae top songs de un artista."""
    artist_data = music_client.get_artist(artist_id)
    return parse_top_songs_v2(artist_data, _ytmusic_client())

def get_albums(artist_id: str, limit: int = 10) -> list:
    """Trae albums de un artista."""
    raw = music_client.browse(artist_id)
    contents = parse_contents(raw)
    albums_sec = find_albums_section(contents)
    if not albums_sec:
        return []
    return parse_albums(albums_sec)[:limit]

def get_singles(artist_id: str, limit: int = 10) -> list:
    """Trae singles/EPs de un artista."""
    raw = music_client.browse(artist_id)
    contents = parse_contents(raw)
    singles_sec = find_singles_section(contents)
    if not singles_sec:
        return []
    return parse_singles_eps(singles_sec)[:limit]

def get_related(artist_id: str) -> list:
    """Trae artistas relacionados."""
    raw = music_client.browse(artist_id)
    contents = parse_contents(raw)
    rel_sec = pick_related_artists_section(contents)
    if not rel_sec:
        return []
    return parse_related_artists(rel_sec)

def get_more_from_artist(artist_id: str, exclude_album_id: str = None, limit: int = 10) -> list:
    """Trae más albums del artista, excluyendo uno específico."""
    albums = get_albums(artist_id, limit=limit + 1)
    if exclude_album_id:
        albums = [a for a in albums if a.get("id") != exclude_album_id]
    return albums[:limit]

def build_artist_payload(
    artist_id: str,
    header: dict,
    top_songs: list,
    albums: list,
    singles: list,
    related: list,
    has_more: dict,
    events: list | None = None,
    new_releases: list | None = None,
    presenting_id: str | None = None,
) -> dict:
    """Pura. Construye el payload final del artista."""
    payload = {
        "header": header,
        "top_songs": top_songs,
        "albums": albums,
        "singles_eps": singles,
        "has_more": has_more,
        "related": related,
        "upcoming_events": events or [],
    }
    if new_releases:
        payload["new_releases"] = new_releases
    if not albums:
        payload.pop("albums", None)
    if not singles:
        payload.pop("singles_eps", None)
    if not top_songs:
        payload.pop("top_songs", None)
    if presenting_id:
        payload["presenting"] = {"playlistId": presenting_id}    
    return payload

def get_artist(artist_id: str, use_cache: bool = True) -> dict:
    if use_cache:
        cached = get_cached(CacheType.ARTIST, suffix=artist_id)
        if cached:
            return cached

    try:
        results = gather({
            "raw": lambda: music_client.browse(artist_id),
            "artist_data": lambda: music_client.get_artist(artist_id),
        })
        
        raw = results["raw"] or {}
        artist_data = results["artist_data"] or {}
        
        if not raw:
            return {"id": artist_id, "error": "fetch_failed"}
        
        header = parse_header(raw)

        # Sin datos válidos no se cachea
        if not header.get("name"):
            print(f"[artist_service][get_artist][WARN] {artist_id}: header vacío, no se cachea")
            return {"id": artist_id, "error": "service_unavailable"}

        contents = parse_contents(raw)

        artist_name = header.get("name") or ""
        albums_sec = find_albums_section(contents)
        singles_sec = find_singles_section(contents)
        rel_sec = pick_related_artists_section(contents)
        
        albums = parse_albums(albums_sec)[:10] if albums_sec else []
        singles = parse_singles_eps(singles_sec)[:10] if singles_sec else []
        related = parse_related_artists(rel_sec) if rel_sec else []
        
        top_songs = parse_top_songs_v2(artist_data, _ytmusic_client())
        
        albums_section = artist_data.get("albums", {})
        singles_section = artist_data.get("singles", {})
        has_more = {
            "albums": albums_section.get("browseId") is not None and len(albums_section.get("results", [])) >= 10,
            "singles": singles_section.get("browseId") is not None and len(singles_section.get("results", [])) >= 10,
        }
        
        events = []
        if artist_name:
            events = get_events_cached_only(artist_name, limit=10)
            if not events:
                schedule_events_refresh(artist_name)
        
        new_releases = []
        try:
            new_releases = list_new_releases_for_artist(artist_id, limit=8)
        except Exception:
            pass
        
        payload = build_artist_payload(
            artist_id, header, top_songs, albums, singles, related, has_more,
            events=events, new_releases=new_releases
        )
        
        set_cached(CacheType.ARTIST, payload, suffix=artist_id)
        return payload
    
    except Exception as e:
        print(f"[artist_service][get_artist][ERR] {artist_id}: {e}")
        return {"id": artist_id, "error": "service_unavailable"}
    
def get_all_albums(artist_id: str, use_cache: bool = True) -> dict:
    """Trae TODOS los albums del artista."""
    if use_cache:
        cached = get_cached(CacheType.ARTIST_ALBUMS, suffix=artist_id)
        if cached:
            return cached

    try:
        artist_data = music_client.get_artist(artist_id)
        albums_section = artist_data.get("albums", {})
        albums_browse_id = albums_section.get("browseId")
        albums_params = albums_section.get("params")

        if albums_browse_id:
            all_albums_raw = music_client.get_artist_albums(albums_browse_id, albums_params)
        else:
            all_albums_raw = albums_section.get("results", [])

        all_albums_raw = all_albums_raw or []

        albums = [
            {
                "id": album.get("browseId"),
                "title": album.get("title"),
                "year": album.get("year"),
                "thumbnails": album.get("thumbnails", []),
            }
            for album in all_albums_raw
        ]

        result = {
            "artist_id": artist_id,
            "total": len(albums),
            "albums": albums,
        }

        set_cached(CacheType.ARTIST_ALBUMS, result, suffix=artist_id)
        return result

    except Exception as e:
        print(f"[artist_service][get_all_albums][ERR] {artist_id}: {e}")
        return {"artist_id": artist_id, "error": str(e)}
    
def get_all_singles(artist_id: str, use_cache: bool = True) -> dict:
    """Trae TODOS los singles/EPs del artista con info enriquecida."""
    if use_cache:
        cached = get_cached(CacheType.ARTIST_SINGLES, suffix=artist_id)
        if cached:
            return cached

    try:
        artist_data = music_client.get_artist(artist_id)
        singles_section = artist_data.get("singles", {})
        singles_browse_id = singles_section.get("browseId")
        singles_params = singles_section.get("params")

        if singles_browse_id:
            all_singles_raw = music_client.get_artist_albums(singles_browse_id, singles_params)
        else:
            all_singles_raw = singles_section.get("results", [])

        all_singles_raw = all_singles_raw or []

        # Enriquecer cada single con type y trackCount en paralelo
        def fetch_single_info(single):
            browse_id = single.get("browseId")
            album_info = music_client.get_album(browse_id) if browse_id else {}
            return {
                "id": browse_id,
                "title": single.get("title"),
                "type": album_info.get("type", single.get("type", "Single")),
                "year": album_info.get("year"),
                "thumbnails": single.get("thumbnails", []),
                "trackCount": album_info.get("trackCount"),
            }

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=10) as executor:
            singles = list(executor.map(fetch_single_info, all_singles_raw))

        result = {
            "artist_id": artist_id,
            "total": len(singles),
            "singles": singles,
        }

        set_cached(CacheType.ARTIST_SINGLES, result, suffix=artist_id)
        return result

    except Exception as e:
        print(f"[artist_service][get_all_singles][ERR] {artist_id}: {e}")
        return {"artist_id": artist_id, "error": str(e)}