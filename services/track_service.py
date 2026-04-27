"""
Lógica de negocio para tracks.
Lyrics, related, up_next.
"""
from services.cache_service import get_cached_legacy, set_cached_legacy
from shared.clients import _ytmusic_client
from utils.related_parser import parse_related_sections

LYRICS_TTL = 12 * 60 * 60
RELATED_TTL = 12 * 60 * 60
UPNEXT_TTL = 6 * 60 * 60

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

def best_thumb_url(track: dict) -> str | None:
    thumbs = track.get("thumbnail") or track.get("thumbnails") or []
    if isinstance(thumbs, str):
        return thumbs.strip() or None
    if isinstance(thumbs, dict):
        u = thumbs.get("url")
        return u.strip() if isinstance(u, str) and u.strip() else None
    if isinstance(thumbs, list):
        for th in reversed(thumbs):
            if isinstance(th, dict) and th.get("url"):
                return th["url"].strip() if isinstance(th["url"], str) else None
            if isinstance(th, str) and th.strip():
                return th.strip()
    return None

""" TODO: MOVE TO UTILS NOT NEEDED FOR NOW """
def extract_artist_info(track: dict) -> tuple[str | None, str | None, list]:
    """Extrae artist_name, artist_id, artist_ids de un track."""
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

    return artist_name, artist_id, artist_ids

def extract_album_info(track: dict) -> tuple[str | None, str | None]:
    """Extrae album_id, album_name de un track."""
    album = track.get("album") or {}
    if not isinstance(album, dict):
        album = {}
    album_id = track.get("album_id") or album.get("id")
    album_name = track.get("album_name") or album.get("name")
    return album_id, album_name

def extract_duration_seconds(track: dict) -> int | None:
    """Extrae duration_seconds de un track."""
    length_seconds = track.get("lengthSeconds") or track.get("duration_seconds")
    if isinstance(length_seconds, int):
        return length_seconds
    if isinstance(length_seconds, str) and length_seconds.strip().isdigit():
        return int(length_seconds.strip())
    duration = track.get("duration") or track.get("length")
    return duration_to_seconds(duration)

def normalize_track_item(track: dict) -> dict:
    if not isinstance(track, dict):
        track = {}

    video_id = track.get("videoId") or track.get("id")
    title = track.get("title")
    album_id, album_name = extract_album_info(track)

    return {
    "id": video_id,
    "title": title,
    "artists": track.get("artists") or [],
    "album_id": album_id,
    "album_name": album_name,
    "thumbnail": best_thumb_url(track),
    "duration": track.get("duration") or track.get("length"),
    "duration_seconds": extract_duration_seconds(track),
}

def filter_related_sections(sections: list) -> list:
    """Filtra secciones excluidas de related."""
    return [
        section for section in sections
        if isinstance(section, dict) and section.get("title") not in EXCLUDED_RELATED_SECTIONS
    ]

def build_lyrics_result(
    ok: bool,
    lyrics=None,
    source: str | None = None,
    has_timestamps: bool = False,
    reason: str | None = None,
) -> dict:
    if ok:
        return {
            "ok": True,
            "lyrics": lyrics,
            "source": source,
            "has_timestamps": has_timestamps,
        }
    return {"ok": False, "reason": reason}

def build_error_result(reason: str, detail: str | None = None) -> dict:
    result = {"ok": False, "reason": reason}
    if detail:
        result["detail"] = detail
    return result

def serialize_lyric_line(line) -> dict:
    """Convierte un LyricLine (dataclass) o dict a dict plano."""
    if isinstance(line, dict):
        return {
            "text": line.get("text"),
            "start_time": line.get("start_time"),
            "end_time": line.get("end_time"),
            "id": line.get("id"),
        }
    return {
        "text": getattr(line, "text", None),
        "start_time": getattr(line, "start_time", None),
        "end_time": getattr(line, "end_time", None),
        "id": getattr(line, "id", None),
    }

# ── IO ───────────────────────────────────────────────────
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

def ensure_artists(artists: list | None, album_id: str | None = None) -> list:
    """
    Garantiza que artists tenga ids cuando sea posible.
    Si detecta colab unparsed (1 entry, id=null, name concatenado),
    busca el album e intenta resolver via included_artists.
    Si no es el caso roto: devuelve tal cual.
    """
    if not isinstance(artists, list) or not artists:
        return artists or []

    # Si no es el caso roto, salir rapido
    if not (
        len(artists) == 1
        and isinstance(artists[0], dict)
        and artists[0].get("id") is None
        and artists[0].get("name")
    ):
        return artists

    # lazy import para evitar circular
    from utils.album_parser import _try_fix_collab_artists
    from services.album_service import get_album

    included = []
    if album_id:
        try:
            album_payload = get_album(album_id) or {}
            included = (album_payload.get("info") or {}).get("included_artists") or []
        except Exception as e:
            print(f"[track_service][ensure_artists][WARN] {album_id}: {e}")

    return _try_fix_collab_artists(artists, included)        

def get_lyrics(video_id: str) -> dict:
    ck = f"lyrics:v2:{video_id}"
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
            out = build_lyrics_result(False, reason="no_lyrics")
            set_cached_legacy(ck, out, 5 * 60)
            return out

        data = yt.get_lyrics(browse_id, timestamps=True) or {}
        raw_lyrics = data.get("lyrics")
        has_timestamps = bool(data.get("hasTimestamps"))

        if has_timestamps and isinstance(raw_lyrics, list):
            lyrics_payload = [serialize_lyric_line(line) for line in raw_lyrics]
        else:
            lyrics_payload = raw_lyrics
            has_timestamps = False

        out = build_lyrics_result(
            True,
            lyrics=lyrics_payload,
            source=data.get("source"),
            has_timestamps=has_timestamps,
        )
        set_cached_legacy(ck, out, LYRICS_TTL)
        return out

    except Exception as e:
        print(f"[track_service][get_lyrics][ERR] {video_id}: {e}")
        return build_error_result("error", str(e))
    
def get_related(video_id: str) -> dict:
    ck = f"related:{video_id}"
    cached = get_cached_legacy(ck)
    if cached is not None:
        return cached

    try:
        yt = _ytmusic_client()
        watch = yt.get_watch_playlist(videoId=video_id)

        if not watch:
            return build_error_result("no_watch_playlist")

        rb = watch.get("related")
        browse_id = rb.get("browseId") if isinstance(rb, dict) else rb

        if not browse_id:
            return build_error_result("no_browse_id")

        related_data = yt.get_song_related(browse_id)
        if isinstance(related_data, list):
            related_data = filter_related_sections(related_data)
            related_data = parse_related_sections(related_data)

        out = {"ok": True, "related": related_data}
        set_cached_legacy(ck, out, RELATED_TTL)
        return out

    except Exception as e:
        print(f"[track_service][get_related][ERR] {video_id}: {e}")
        return build_error_result("error", str(e))

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
        return build_error_result("error", str(e))

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
            return build_error_result("no_tracks")

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
        set_cached_legacy(ck, out, UPNEXT_TTL)
        return out

    except Exception as e:
        print(f"[track_service][get_up_next][ERR] {video_id}: {e}")
        return build_error_result("error", str(e))