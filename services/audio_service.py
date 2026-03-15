"""
Audio service: extracción, cache y streaming.
"""
import os
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import Tuple, Any

import requests
from requests.adapters import HTTPAdapter
from fastapi.responses import StreamingResponse
from pytubefix import YouTube as PytubeYouTube

from shared.clients import _ydl_global

# ── CONFIG ───────────────────────────────────────────────
MAX_WORKERS = 8
WARM_MAX_WORKERS = 10
WARM_ENABLED = False
URL_TTL = 1800
_WARM_BURST = 20
_WARM_DEDUP_TTL = 45

POSSIBLE_COOKIE_PATHS = [
    "/root/musicappbackend/cookies.txt",
    os.path.join(os.getcwd(), "cookies.txt"),
    os.path.join(os.path.dirname(__file__), "..", "cookies.txt"),
]
COOKIEFILE = next(
    (p for p in POSSIBLE_COOKIE_PATHS if os.path.exists(p) and os.path.getsize(p) > 0),
    None,
)

# ── CACHES ───────────────────────────────────────────────
_cache: dict[str, dict] = {}
_FORCE_CACHE: dict[str, dict] = {}
_FORCE_TTL = 24 * 60 * 60
_ARTIST_CACHE: dict[str, dict] = {}
_WARM_INFLIGHT: dict[str, float] = {}

# ── HTTP SESSIONS ────────────────────────────────────────
def _create_session(pool_size: int, pool_block: bool = True) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "*/*", "Connection": "keep-alive"})
    adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size, max_retries=0, pool_block=pool_block)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

_SESSION_SHORT = _create_session(80)
_SESSION_STREAM = _create_session(100, pool_block=False)

_BACKGROUND_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS)
_WARM_EXECUTOR: ThreadPoolExecutor | None = None

def _get_warm_executor() -> ThreadPoolExecutor:
    global _WARM_EXECUTOR
    if _WARM_EXECUTOR is None:
        _WARM_EXECUTOR = ThreadPoolExecutor(max_workers=WARM_MAX_WORKERS)
    return _WARM_EXECUTOR

_norm_re_strip = re.compile(r"(\(|\[).{0,80}?(\)|\])", re.IGNORECASE)
_norm_re_noise = re.compile(r"\b(official\s*video|video\s*oficial|video\s*clip|lyrics?|audio\s*only|HD|4K)\b", re.IGNORECASE)

def _ttl_from_url(url: str) -> int:
    """Extrae TTL de la URL de YouTube."""
    try:
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        now = int(time.time())
        if "expire" in qs:
            exp = int(qs["expire"][0])
            return max(60, min(90 * 60, exp - now - 120))
        if "x-goog-expires" in qs:
            ttl = int(qs["x-goog-expires"][0])
            return max(60, min(90 * 60, ttl - 120))
    except Exception:
        pass
    return URL_TTL

def pick_best_audio(info: dict) -> Tuple[str | None, dict | None, dict]:
    """Selecciona el mejor formato de audio de los disponibles."""
    fmts = info.get("formats") or []
    for f in reversed(fmts):
        if f.get("vcodec") in (None, "none") and f.get("acodec") not in (None, "none") and f.get("url"):
            return f.get("url"), f, {"reason": "best_available"}
    return info.get("url"), None, {"reason": "fallback"}

def _guess_audio_media_type(url: str, hdr_ct: str | None) -> str:
    """Infiere el MIME type del audio."""
    if hdr_ct and hdr_ct != "application/octet-stream":
        return hdr_ct
    u = url.lower()
    if ".m4a" in u or ".mp4" in u:
        return "audio/mp4"
    if ".webm" in u or ".weba" in u:
        return "audio/webm"
    if "mime=" in u:
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        mime = qs.get("mime", [None])[0]
        if mime:
            return mime
    return "audio/*"

def _ct_base(ct: str | None) -> str | None:
    """Extrae el MIME base sin parámetros."""
    if not ct:
        return None
    return ct.split(";", 1)[0].strip()

def is_cache_valid(entry: dict | None, now: float) -> bool:
    """Verifica si una entrada de cache sigue válida."""
    if not entry or not entry.get("direct_url"):
        return False
    age = now - entry["ts"]
    ttl = entry.get("ttl", URL_TTL)
    return age < ttl

def build_cache_entry(info: dict, url: str, client: str, now: float) -> dict:
    """Construye entrada de cache."""
    return {
        "info": info,
        "direct_url": url,
        "client": client,
        "ts": now,
        "ttl": _ttl_from_url(url),
    }

def _extract_best_url(video_id: str) -> Tuple[dict, str, str]:
    try:
        yt = PytubeYouTube(
            f"https://www.youtube.com/watch?v={video_id}",
            client="ANDROID_VR"
        )
        stream = yt.streams.filter(only_audio=True).order_by("abr").last()
        if stream and stream.url:
            return {}, stream.url, "pytubefix"
        raise ValueError("no audio stream")
    except Exception as e:
        print(f"[extract] pytubefix FAILED ({type(e).__name__}: {e}), trying yt-dlp...")

    ydl = _ydl_global()
    info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False, process=True)
    url, best_fmt, diag = pick_best_audio(info)
    if not url:
        raise RuntimeError("no_audio_format")
    return info, url, "yt-dlp"

def _get_or_extract(video_id: str, _force: bool = False) -> dict:
    t0 = time.time()
    if not _force:
        ent = _cache.get(video_id)
        if is_cache_valid(ent, t0):
            return ent

    info, url, client = _extract_best_url(video_id)
    now = time.time()
    #print(f"[audio] EXTRACTED {video_id} via {client}: {int((now - t0) * 1000)}ms")
    data = build_cache_entry(info, url, client, now)
    _cache[video_id] = data
    return data

def get_audio_info(video_id: str) -> dict:
    return _get_or_extract(video_id)

def stream_from_url(url: str, range_header: str | None) -> StreamingResponse:
    ORIGIN_CHUNK = 256 * 1024

    def open_req(extra_range: str | None):
        hdrs = {"Accept-Encoding": "identity"}
        if extra_range:
            hdrs["Range"] = extra_range
        elif range_header:
            hdrs["Range"] = range_header
        r = _SESSION_STREAM.get(url, headers=hdrs, stream=True, timeout=(5, 120), allow_redirects=True)
        r.raw.decode_content = False
        return r

    r = open_req(None)
    resp_headers = {"Accept-Ranges": "bytes", "Connection": "keep-alive"}

    ct = _ct_base(r.headers.get("Content-Type"))
    cr = r.headers.get("Content-Range")
    cl = r.headers.get("Content-Length")

    if cr:
        resp_headers["Content-Range"] = cr
    if cl:
        resp_headers["Content-Length"] = cl

    media_type = _ct_base(ct if ct else _guess_audio_media_type(url, None)) or "audio/*"

    status = r.status_code
    if range_header and range_header.lower().startswith("bytes=") and cr:
        status = 206

    def streamer():
        nonlocal r
        sent = 0
        tried_resume = False
        try:
            while True:
                try:
                    for chunk in r.iter_content(ORIGIN_CHUNK):
                        if not chunk:
                            break
                        sent += len(chunk)
                        yield chunk
                    break
                except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError,
                        requests.exceptions.ReadTimeout, TimeoutError):
                    if tried_resume:
                        break
                    tried_resume = True
                    try:
                        if range_header and range_header.lower().startswith("bytes="):
                            base = range_header.split("=", 1)[1].split("-", 1)[0]
                            base_offset = int(base) if base else 0
                            new_start = base_offset + sent
                        else:
                            new_start = sent
                        try:
                            r.close()
                        except Exception:
                            pass
                        r = open_req(f"bytes={new_start}-")
                        cr2 = r.headers.get("Content-Range")
                        cl2 = r.headers.get("Content-Length")
                        if cr2:
                            resp_headers["Content-Range"] = cr2
                        if cl2:
                            resp_headers["Content-Length"] = cl2
                        continue
                    except Exception:
                        break
        except (BrokenPipeError, ConnectionResetError, GeneratorExit):
            pass
        finally:
            try:
                r.close()
            except Exception:
                pass

    return StreamingResponse(streamer(), media_type=media_type, headers=resp_headers, status_code=status)

def _probe_url(url: str) -> bool:
    try:
        r = _SESSION_SHORT.get(url, headers={"Range": "bytes=0-1"}, stream=True, timeout=(1, 3), allow_redirects=True)
        ok = r.status_code in (200, 206)
        r.close()
        return ok
    except Exception:
        return False

def _warm_one(video_id: str) -> None:
    try:
        data = _get_or_extract(video_id)
        _probe_url(data["direct_url"])
    except Exception:
        pass

def schedule_warm(ids: list[str]) -> None:
    if not ids or not WARM_ENABLED:
        return
    now = time.time()
    uniq = [v for v in dict.fromkeys(ids) if v]
    planned = []
    for v in uniq[:_WARM_BURST]:
        ts = _WARM_INFLIGHT.get(v, 0)
        if now - ts > _WARM_DEDUP_TTL:
            _WARM_INFLIGHT[v] = now
            planned.append(v)
    if not planned:
        return
    ex = _get_warm_executor()
    for v in planned:
        try:
            ex.submit(_warm_one, v)
        except Exception:
            pass

def get_warm_burst() -> int:
    return _WARM_BURST