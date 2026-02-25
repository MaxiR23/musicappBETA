# routes/tracks.py
"""
Endpoints de tracks: lyrics, related, upnext
"""
from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse

from services.cache_service import get_cached_legacy, set_cached_legacy, set_cached

from shared.clients import _ytmusic_client

router = APIRouter()

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTES
# ═══════════════════════════════════════════════════════════════════════════════

_LYRICS_TTL = 12 * 60 * 60  # 12h
_RELATED_TTL = 12 * 60 * 60  # 12h
_UPNEXT_TTL = 6 * 60 * 60  # 6h

_EXCLUDED_RELATED_SECTIONS = {
    "Recommended playlists",
    "Other performances",
}

# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _duration_to_seconds(d: str | None) -> int | None:
    if not d or not isinstance(d, str):
        return None
    s = d.strip()
    if not s:
        return None
    try:
        parts = [int(p) for p in s.split(":")]
    except Exception:
        return None

    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        mm, ss = parts
        return mm * 60 + ss
    if len(parts) == 3:
        hh, mm, ss = parts
        return hh * 3600 + mm * 60 + ss
    return None


def _best_thumb_url(track: dict) -> str | None:
    thumbs = track.get("thumbnail") or track.get("thumbnails") or []
    # Caso: thumbnail ya es string
    if isinstance(thumbs, str):
        return thumbs.strip() or None

    # Caso: thumbnail dict
    if isinstance(thumbs, dict):
        u = thumbs.get("url")
        return (u.strip() if isinstance(u, str) and u.strip() else None)

    # Caso: lista de thumbs (dicts o strings)
    if isinstance(thumbs, list):
        for th in reversed(thumbs):
            if isinstance(th, dict) and th.get("url"):
                u = th["url"]
                return u.strip() if isinstance(u, str) and u.strip() else None
            if isinstance(th, str) and th.strip():
                return th.strip()

    return None


def _normalize_track_item(track: dict) -> dict:
    if not isinstance(track, dict):
        track = {}

    video_id = track.get("videoId") or track.get("id")

    title = track.get("title")

    # artists
    artists_list = track.get("artists") or []
    if not isinstance(artists_list, list):
        artists_list = []

    artist_ids = []
    seen = set()
    artist_names = []

    for a in artists_list:
        if not isinstance(a, dict):
            continue
        n = a.get("name")
        i = a.get("id")
        if isinstance(n, str) and n.strip():
            artist_names.append(n.strip())
        if isinstance(i, str) and i.strip() and i not in seen:
            seen.add(i)
            artist_ids.append(i)

    artist_name = track.get("artistName")
    if not artist_name:
        if artist_names:
            artist_name = ", ".join(artist_names)
        else:
            author = track.get("author")
            artist_name = author.strip() if isinstance(author, str) and author.strip() else None

    artist_id = track.get("artistId")
    if not artist_id:
        artist_id = artist_ids[0] if artist_ids else None

    # album
    album = track.get("album") or {}
    if not isinstance(album, dict):
        album = {}

    album_id = track.get("albumId") or album.get("id")
    album_name = track.get("albumName") or album.get("name")

    # duration
    duration = track.get("duration") or track.get("length")
    length_seconds = track.get("lengthSeconds") or track.get("durationSeconds") or track.get("duration_seconds")

    duration_seconds = None
    if isinstance(length_seconds, int):
        duration_seconds = length_seconds
    elif isinstance(length_seconds, str) and length_seconds.strip().isdigit():
        duration_seconds = int(length_seconds.strip())
    else:
        duration_seconds = _duration_to_seconds(duration)

    return {
        "id": video_id,
        "title": title,

        "artistName": artist_name,
        "artistId": artist_id,
        "artistIds": artist_ids,
        "artists": artists_list,

        "albumId": album_id,
        "albumName": album_name,

        "thumbnail": _best_thumb_url(track),
        "duration": duration,
        "durationSeconds": duration_seconds,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# LYRICS
# ═══════════════════════════════════════════════════════════════════════════════

def _lyrics_browse_id_from_watch(yt, video_id: str) -> str | None:
    wp = yt.get_watch_playlist(videoId=video_id) or {}
    lyr_field = wp.get("lyrics")
    if isinstance(lyr_field, dict):
        return lyr_field.get("browseId") or (lyr_field.get("browseEndpoint") or {}).get("browseId")
    if isinstance(lyr_field, str):
        s = lyr_field.strip()
        return s or None
    return None


def _get_track_lyrics_backend(video_id: str) -> dict:
    ck = f"lyrics:{video_id}"
    cached = get_cached_legacy(ck)
    if cached is not None:
        return cached

    yt = _ytmusic_client()
    b = _lyrics_browse_id_from_watch(yt, video_id)
    if not b:
        out = {"ok": False, "reason": "no_lyrics"}
        # cache corto negativo para no insistir
        set_cached_legacy(ck, out, 5 * 60)
        return out

    data = yt.get_lyrics(b) or {}
    out = {
        "ok": True,
        "lyrics": data.get("lyrics"),
        "source": data.get("source"),
    }
    set_cached_legacy(ck, out, _LYRICS_TTL)
    return out


@router.get("/tracks/{track_id}/lyrics")
def get_track_lyrics(track_id: str = Path(...)):
    """
    Devuelve letras para un videoId si YT Music las expone.
    """
    try:
        res = _get_track_lyrics_backend(track_id)
        if not res.get("ok"):
            return JSONResponse(status_code=404, content=res)
        return res
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "lyrics_failed", "detail": f"{type(e).__name__}: {e}"}
        )


# ═══════════════════════════════════════════════════════════════════════════════
# RELATED
# ═══════════════════════════════════════════════════════════════════════════════

def _get_track_related_backend(video_id: str) -> dict:
    ck = f"related:{video_id}"
    cached = get_cached_legacy(ck)
    if cached is not None:
        return cached

    yt = _ytmusic_client()
    
    try:
        # Obtenemos el watch playlist
        watch = yt.get_watch_playlist(videoId=video_id)
        if not watch:
            out = {"ok": False, "reason": "no_watch_playlist"}
            set_cached_legacy(ck, out, 5 * 60)
            return out
        
        # El browseId viene en el campo "related"
        rb = watch.get("related")
        browse_id = rb.get("browseId") if isinstance(rb, dict) else rb
        
        if not browse_id:
            out = {"ok": False, "reason": "no_browse_id"}
            set_cached_legacy(ck, out, 5 * 60)
            return out
        
        # Obtenemos las canciones relacionadas
        related_data = yt.get_song_related(browse_id)
        
        # Filtramos las secciones no deseadas
        if isinstance(related_data, list):
            related_data = [
                section for section in related_data
                if section.get("title") not in _EXCLUDED_RELATED_SECTIONS
            ]
        
        out = {
            "ok": True,
            "related": related_data
        }
        set_cached_legacy(ck, out, _RELATED_TTL)
        return out
        
    except Exception as e:
        out = {"ok": False, "reason": "error", "detail": str(e)}
        set_cached_legacy(ck, out, 1 * 60)
        return out


@router.get("/tracks/{track_id}/related")
def get_track_related(track_id: str = Path(...)):
    """
    Devuelve canciones relacionadas para un videoId.
    """
    try:
        res = _get_track_related_backend(track_id)
        if not res.get("ok"):
            return JSONResponse(status_code=404, content=res)
        return res
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "related_failed", "detail": f"{type(e).__name__}: {e}"}
        )


@router.get("/tracks/{track_id}/related-raw")
def get_track_related_raw(track_id: str = Path(...)):
    """
    Devuelve TODO el related crudo (sin filtros) para un videoId.
    Solo para debug.
    """
    yt = _ytmusic_client()

    try:
        watch = yt.get_watch_playlist(videoId=track_id)
        if not watch:
            return JSONResponse(status_code=404, content={"ok": False, "reason": "no_watch_playlist", "watch": watch})

        rb = watch.get("related")
        browse_id = rb.get("browseId") if isinstance(rb, dict) else rb

        if not browse_id:
            return JSONResponse(status_code=404, content={
                "ok": False,
                "reason": "no_browse_id",
                "watch_related_field": rb,
                "watch_keys": list(watch.keys()) if isinstance(watch, dict) else None
            })

        related_data = yt.get_song_related(browse_id)

        # Respuesta RAW tal cual
        return {
            "ok": True,
            "trackId": track_id,
            "browseId": browse_id,
            "watch_related_field": rb,
            "related_raw": related_data,
        }

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "related_raw_failed", "detail": f"{type(e).__name__}: {e}"}
        )


# ═══════════════════════════════════════════════════════════════════════════════
# UP NEXT / QUEUE
# ═══════════════════════════════════════════════════════════════════════════════

def _get_track_upnext_backend(video_id: str) -> dict:
    ck = f"upnext:{video_id}"
    cached = get_cached_legacy(ck)
    if cached is not None:
        return cached

    yt = _ytmusic_client()

    try:
        song_raw = yt.get_song(video_id) or {}
        video_details = song_raw.get("videoDetails") or {}

        watch = yt.get_watch_playlist(videoId=video_id) or {}
        tracks = watch.get("tracks") or []

        if not tracks:
            out = {"ok": False, "reason": "no_tracks"}
            set_cached_legacy(ck, out, 5 * 60)
            return out

        # current normalizado con el mismo shape
        current_raw = {
            "videoId": video_details.get("videoId") or video_id,
            "title": video_details.get("title"),
            "author": video_details.get("author"),
            "lengthSeconds": video_details.get("lengthSeconds"),
        }
        current = _normalize_track_item(current_raw)

        upnext = []
        for t in tracks:
            if isinstance(t, dict):
                upnext.append(_normalize_track_item(t))

        out = {
            "ok": True,
            "current": current,
            "upNext": upnext,
            "autoplay": watch.get("autoplay"),
        }
        set_cached_legacy(ck, out, _UPNEXT_TTL)
        return out

    except Exception as e:
        out = {"ok": False, "reason": "error", "detail": str(e)}
        set_cached_legacy(ck, out, 1 * 60)
        return out


@router.get("/tracks/{track_id}/upnext")
def get_track_upnext(track_id: str = Path(...)):
    """
    Devuelve la cola de reproducción (up next) para un trackId.
    """
    try:
        res = _get_track_upnext_backend(track_id)
        if not res.get("ok"):
            return JSONResponse(status_code=404, content=res)
        return res
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "upnext_failed", "detail": f"{type(e).__name__}: {e}"}
        )