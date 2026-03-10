# services/track_service.py
"""
Lógica de negocio para tracks.
Lyrics, related, up_next.
"""
from services.cache_service import get_cached_legacy, set_cached_legacy
from shared.clients import _ytmusic_client
from utils.related_parser import parse_related_sections

LYRICS_TTL = 12 * 60 * 60
RELATED_TTL = 12 * 60 * 60
UPNEXTTTL = 6 * 60 * 60

EXCLUDED_RELATED_SECTIONS = {
    "Recommended playlists",
    "Other performances",
}

def duration_to_seconds(d: str | None) -> int | None:
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

def ensure_duration_seconds(track_id: str, duration_seconds=None) -> int | None:
    if duration_seconds:
        return duration_seconds
    if not track_id:
        return None
    try:
        yt = _ytmusic_client()
        song_raw = yt.get_song(track_id) or {}
        seconds = (song_raw.get("videoDetails") or {}).get("lengthSeconds")
        if isinstance(seconds, int):
            return seconds
        if isinstance(seconds, str) and seconds.strip().isdigit():
            return int(seconds.strip())
        return None
    except Exception:
        return None

def best_thumb_url(track: dict) -> str | None:
    thumbs = track.get("thumbnail") or track.get("thumbnails") or []
    if isinstance(thumbs, str):
        return thumbs.strip() or None
    if isinstance(thumbs, dict):
        u = thumbs.get("url")
        return (u.strip() if isinstance(u, str) and u.strip() else None)
    if isinstance(thumbs, list):
        for th in reversed(thumbs):
            if isinstance(th, dict) and th.get("url"):
                u = th["url"]
                return u.strip() if isinstance(u, str) and u.strip() else None
            if isinstance(th, str) and th.strip():
                return th.strip()
    return None

def normalize_track_item(track: dict) -> dict:
    if not isinstance(track, dict):
        track = {}

    video_id = track.get("videoId") or track.get("id")
    title = track.get("title")

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

    artist_name = track.get("artist_name")
    if not artist_name:
        if artist_names:
            artist_name = ", ".join(artist_names)
        else:
            author = track.get("author")
            artist_name = author.strip() if isinstance(author, str) and author.strip() else None

    artist_id = track.get("artist_id")
    if not artist_id:
        artist_id = artist_ids[0] if artist_ids else None

    album = track.get("album") or {}
    if not isinstance(album, dict):
        album = {}

    album_id = track.get("album_id") or album.get("id")
    album_name = track.get("album_name") or album.get("name")

    duration = track.get("duration") or track.get("length")
    length_seconds = track.get("lengthSeconds") or track.get("duration_seconds")

    duration_seconds = None
    if isinstance(length_seconds, int):
        duration_seconds = length_seconds
    elif isinstance(length_seconds, str) and length_seconds.strip().isdigit():
        duration_seconds = int(length_seconds.strip())
    else:
        duration_seconds = duration_to_seconds(duration)

    return {
        "id": video_id,
        "title": title,
        "artist_name": artist_name,
        "artist_id": artist_id,
        "artist_ids": artist_ids,
        "artists": artists_list,
        "album_id": album_id,
        "album_name": album_name,
        "thumbnail": best_thumb_url(track),
        "duration": duration,
        "duration_seconds": duration_seconds,
    }

def get_lyrics(video_id: str) -> dict:
    ck = f"lyrics:{video_id}"
    cached = get_cached_legacy(ck)
    if cached is not None:
        return cached

    try:
        yt = _ytmusic_client()
        wp = yt.get_watch_playlist(videoId=video_id) or {}
        lyr_field = wp.get("lyrics")

        browse_id = None
        if isinstance(lyr_field, dict):
            browse_id = lyr_field.get("browseId") or (lyr_field.get("browseEndpoint") or {}).get("browseId")
        elif isinstance(lyr_field, str):
            browse_id = lyr_field.strip() or None

        if not browse_id:
            # La canción genuinamente no tiene lyrics — cachear para no volver a buscar
            out = {"ok": False, "reason": "no_lyrics"}
            set_cached_legacy(ck, out, 5 * 60)
            return out

        data = yt.get_lyrics(browse_id) or {}
        out = {"ok": True, "lyrics": data.get("lyrics"), "source": data.get("source")}
        set_cached_legacy(ck, out, LYRICS_TTL)
        return out

    except Exception as e:
        print(f"[track_service][get_lyrics][ERR] {video_id}: {e}")
        # Error del servicio — no cachear
        return {"ok": False, "reason": "error", "detail": str(e)}

def get_related(video_id: str) -> dict:
    ck = f"related:{video_id}"
    cached = get_cached_legacy(ck)
    if cached is not None:
        return cached

    try:
        yt = _ytmusic_client()
        watch = yt.get_watch_playlist(videoId=video_id)

        if not watch:
            # No cachear — puede ser falla del servicio
            return {"ok": False, "reason": "no_watch_playlist"}

        rb = watch.get("related")
        browse_id = rb.get("browseId") if isinstance(rb, dict) else rb

        if not browse_id:
            # No cachear — puede ser falla del servicio
            return {"ok": False, "reason": "no_browse_id"}

        related_data = yt.get_song_related(browse_id)
        if isinstance(related_data, list):
            related_data = [
                section for section in related_data
                if isinstance(section, dict) and section.get("title") not in EXCLUDED_RELATED_SECTIONS
            ]
            related_data = parse_related_sections(related_data)

        out = {"ok": True, "related": related_data}
        set_cached_legacy(ck, out, RELATED_TTL)
        return out

    except Exception as e:
        print(f"[track_service][get_related][ERR] {video_id}: {e}")
        # Error del servicio — no cachear
        return {"ok": False, "reason": "error", "detail": str(e)}

def get_related_raw(video_id: str) -> dict:
    try:
        yt = _ytmusic_client()
        watch = yt.get_watch_playlist(videoId=video_id)

        if not watch:
            return {"ok": False, "reason": "no_watch_playlist", "watch": watch}

        rb = watch.get("related")
        browse_id = rb.get("browseId") if isinstance(rb, dict) else rb

        if not browse_id:
            return {
                "ok": False,
                "reason": "no_browse_id",
                "watch_related_field": rb,
                "watch_keys": list(watch.keys()) if isinstance(watch, dict) else None,
            }

        related_data = yt.get_song_related(browse_id)
        return {
            "ok": True,
            "track_id": video_id,
            "browse_id": browse_id,
            "watch_related_field": rb,
            "related_raw": related_data,
        }

    except Exception as e:
        return {"ok": False, "reason": "error", "detail": str(e)}

def get_up_next(video_id: str) -> dict:
    ck = f"up_next:{video_id}"
    cached = get_cached_legacy(ck)
    if cached is not None:
        return cached

    try:
        yt = _ytmusic_client()
        song_raw = yt.get_song(video_id) or {}
        video_details = song_raw.get("videoDetails") or {}

        watch = yt.get_watch_playlist(videoId=video_id) or {}
        tracks = watch.get("tracks") or []

        if not tracks:
            # No cachear — puede ser falla del servicio
            return {"ok": False, "reason": "no_tracks"}

        current_raw = {
            "videoId": video_details.get("videoId") or video_id,
            "title": video_details.get("title"),
            "author": video_details.get("author"),
            "lengthSeconds": video_details.get("lengthSeconds"),
        }
        current = normalize_track_item(current_raw)
        up_next = [normalize_track_item(t) for t in tracks if isinstance(t, dict)]

        out = {
            "ok": True,
            "current": current,
            "up_next": up_next,
            "autoplay": watch.get("autoplay"),
        }
        set_cached_legacy(ck, out, UPNEXTTTL)
        return out

    except Exception as e:
        print(f"[track_service][get_up_next][ERR] {video_id}: {e}")
        # Error del servicio — no cachear
        return {"ok": False, "reason": "error", "detail": str(e)}