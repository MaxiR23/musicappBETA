# routes/audio.py
"""
Endpoints de audio: play, prefetch, warm
Incluye lógica de extracción y streaming
"""
import os
import re
import time
import tempfile
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Query, Body, Request
from fastapi.responses import StreamingResponse, JSONResponse, RedirectResponse

import requests
from requests.adapters import HTTPAdapter

from pytubefix import YouTube as PytubeYouTube
from shared.clients import _ydl_global

router = APIRouter()

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

MAX_WORKERS = 8
WARM_MAX_WORKERS = 10
WARM_ENABLED = False

URL_TTL = 1800  # default TTL

_WARM_BURST = 20
_WARM_DEDUP_TTL = 45

# ═══════════════════════════════════════════════════════════════════════════════
# COOKIES
# ═══════════════════════════════════════════════════════════════════════════════
POSSIBLE_COOKIE_PATHS = [
    "/root/musicappbackend/cookies.txt",  # VPS Linux
    os.path.join(os.getcwd(), "cookies.txt"),  # local carpeta backend/
    os.path.join(os.path.dirname(__file__), "..", "cookies.txt"),  # relativo
]

COOKIEFILE = next((p for p in POSSIBLE_COOKIE_PATHS if os.path.exists(p) and os.path.getsize(p) > 0), None)

# ═══════════════════════════════════════════════════════════════════════════════
# CACHES
# ═══════════════════════════════════════════════════════════════════════════════

_cache: dict[str, dict] = {}  # videoId -> {info, direct_url, ttl, ts, served}
_FORCE_CACHE: dict[str, dict] = {}  # OMV->ATV resolver
_FORCE_TTL = 24 * 60 * 60
_ARTIST_CACHE: dict[str, dict] = {}
_WARM_INFLIGHT: dict[str, float] = {}


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP SESSIONS
# ═══════════════════════════════════════════════════════════════════════════════

_SESSION_SHORT = requests.Session()
_SESSION_SHORT.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "*/*", "Connection": "keep-alive"})
_SESSION_SHORT.mount("https://", HTTPAdapter(pool_connections=80, pool_maxsize=80, max_retries=0))
_SESSION_SHORT.mount("http://",  HTTPAdapter(pool_connections=80, pool_maxsize=80, max_retries=0))

_SESSION_STREAM = requests.Session()
_SESSION_STREAM.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "*/*", "Connection": "keep-alive"})
_SESSION_STREAM.mount("https://", HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=0, pool_block=False))
_SESSION_STREAM.mount("http://",  HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=0, pool_block=False))


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTORS
# ═══════════════════════════════════════════════════════════════════════════════

_BACKGROUND_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS)
_WARM_EXECUTOR = None

def _get_warm_executor() -> ThreadPoolExecutor:
    global _WARM_EXECUTOR
    if _WARM_EXECUTOR is None:
        _WARM_EXECUTOR = ThreadPoolExecutor(max_workers=WARM_MAX_WORKERS)
    return _WARM_EXECUTOR


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _ttl_from_url(u: str) -> int:
    try:
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)
        now = int(time.time())
        if "expire" in qs:
            exp = int(qs["expire"][0])
            return max(60, min(90*60, exp - now - 120))
        if "x-goog-expires" in qs:
            ttl = int(qs["x-goog-expires"][0])
            return max(60, min(90*60, ttl - 120))
    except Exception:
        pass
    return URL_TTL


_norm_re_strip = re.compile(r"(\(|\[).{0,80}?(\)|\])", re.IGNORECASE)
_norm_re_noise = re.compile(r"\b(official\s*video|video\s*oficial|video\s*clip|lyrics?|audio\s*only|HD|4K)\b", re.IGNORECASE)


# ═══════════════════════════════════════════════════════════════════════════════
# EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

def pick_best_audio(info: dict):
    fmts = info.get("formats") or []
    
    for f in reversed(fmts):
        if f.get("vcodec") in (None, "none") and f.get("acodec") not in (None, "none") and f.get("url"):
            return f.get("url"), f, {"reason": "best_available"}
    
    return (info.get("url"), None, {"reason": "fallback"})


def _extract_best_url(video_id: str):
    """pytubefix primero (4x más rápido), fallback a yt-dlp si falla."""
    
    # 1) Intentar con pytubefix
    try:
        yt = PytubeYouTube(f"https://www.youtube.com/watch?v={video_id}")
        stream = yt.streams.get_audio_only()
        if stream and stream.url:
            return {"title": yt.title}, stream.url, "pytubefix"
    except Exception as e:
        print(f"[extract] pytubefix FAILED, trying yt-dlp: {type(e).__name__}")
    
    # 2) Fallback a yt-dlp
    try:
        ydl = _ydl_global()
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False, process=True)
        url, best_fmt, diag = pick_best_audio(info)
        if not url:
            raise RuntimeError("no_audio_format")
        return info, url, "yt-dlp"
    except Exception as e:
        raise RuntimeError(f"extract_failed: {type(e).__name__}")


def _get_or_extract(video_id: str, _force: bool = False):
    """Extrae URL directa de audio. Con cache ultra-corta (60s)."""
    now = time.time()

    # 1) Cache
    if not _force:
        ent = _cache.get(video_id)
        if ent and ent.get("direct_url"):
            age = now - ent["ts"]
            ttl = ent.get("ttl", 1800)
            if age < ttl:
                return ent

    # 2) Extracción
    try:
        info1, url1, client1 = _extract_best_url(video_id)
    except Exception as e:
        raise

    # 3) Construir respuesta
    data = {
        "info": info1,
        "direct_url": url1,
        "client": client1,
        "ts": now,
        "ttl": _ttl_from_url(url1),
    }

    # 4) Guardar en cache
    _cache[video_id] = data
    
    return data


def get_audio_info_quick(video_id: str):
    return _get_or_extract(video_id)


def get_audio_info_blocking(video_id: str):
    return _get_or_extract(video_id)


# ═══════════════════════════════════════════════════════════════════════════════
# FS AUDIO CACHE (full file)
# ═══════════════════════════════════════════════════════════════════════════════

_AUDIO_CACHE_DIR = os.path.join(tempfile.gettempdir(), "music_fullcache_v1")
os.makedirs(_AUDIO_CACHE_DIR, exist_ok=True)


def _cache_paths(cache_key: str):
    base = os.path.join(_AUDIO_CACHE_DIR, f"{cache_key}")
    return base + ".bin", base + ".part", base + ".meta"


def _serve_file_range(path: str, range_header: str | None, media_type: str = "audio/mp4") -> StreamingResponse:
    size = os.path.getsize(path)
    if range_header and range_header.lower().startswith("bytes="):
        try:
            rng = range_header.split("=", 1)[1]
            if "-" in rng:
                start_str, end_str = rng.split("-", 1)
                start = int(start_str) if start_str else 0
                end = int(end_str) if end_str else (size - 1)
                start = max(0, min(start, size - 1))
                end = max(start, min(end, size - 1))
            else:
                start = int(rng)
                end = size - 1
        except Exception:
            start, end = 0, size - 1
        length = end - start + 1

        def file_iter():
            with open(path, "rb") as f:
                f.seek(start)
                remaining = length
                chunk = 64 * 1024
                while remaining > 0:
                    to_read = min(chunk, remaining)
                    data = f.read(to_read)
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        headers = {
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Connection": "keep-alive",
        }
        return StreamingResponse(file_iter(), status_code=206, media_type=media_type, headers=headers)

    def file_iter_all():
        with open(path, "rb") as f:
            while True:
                b = f.read(64 * 1024)
                if not b:
                    break
                yield b

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(size),
        "Connection": "keep-alive",
    }
    return StreamingResponse(file_iter_all(), status_code=200, media_type=media_type, headers=headers)


def _download_full_to_cache(audio_url: str, cache_key: str):
    dst_path, tmp_path, meta_path = _cache_paths(cache_key)
    if os.path.exists(dst_path):
        return
    try:
        with _SESSION_STREAM.get(audio_url, stream=True, timeout=(3, 60), allow_redirects=True) as r:
            ct = r.headers.get("Content-Type") or "audio/mp4"
            with open(meta_path, "w", encoding="utf-8") as m:
                m.write(ct)
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(64 * 1024):
                    if not chunk:
                        break
                    f.write(chunk)
        os.replace(tmp_path, dst_path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# NETWORKING / STREAMING
# ═══════════════════════════════════════════════════════════════════════════════

def _probe_url(url: str) -> bool:
    headers = {"Range": "bytes=0-1"}
    try:
        r = _SESSION_SHORT.get(url, headers=headers, stream=True, timeout=(1, 3), allow_redirects=True)
        ok = r.status_code in (200, 206)
        r.close()
        return ok
    except Exception:
        return False


def _guess_audio_media_type(url: str, hdr_ct: str | None) -> str:
    if hdr_ct:
        return hdr_ct
    u = url.lower()
    if ".m4a" in u or ".mp4" in u:
        return "audio/mp4"
    if ".webm" in u or ".weba" in u:
        return "audio/webm"
    return "audio/*"


def _stream_from_url(url: str, range_header: str | None) -> StreamingResponse:
    """Proxy de audio con reintento único."""
    ORIGIN_CHUNK = 256 * 1024

    def open_req(extra_range: str | None):
        hdrs = {"Accept-Encoding": "identity"}
        if range_header:
            hdrs["Range"] = range_header
        if extra_range:
            hdrs["Range"] = extra_range

        r = _SESSION_STREAM.get(
            url,
            headers=hdrs,
            stream=True,
            timeout=(5, 120),
            allow_redirects=True,
        )
        r.raw.decode_content = False
        return r

    r = open_req(None)

    resp_headers = {"Accept-Ranges": "bytes", "Connection": "keep-alive"}
    ct = r.headers.get("Content-Type")
    cr = r.headers.get("Content-Range")
    if cr:
        resp_headers["Content-Range"] = cr

    media_type = ct if ct else _guess_audio_media_type(url, None)

    total_len = None
    if cr and "/" in cr:
        try:
            total_len = int(cr.split("/", 1)[1])
        except Exception:
            total_len = None
    if total_len is None:
        try:
            total_len = int(r.headers.get("Content-Length") or 0) or None
        except Exception:
            total_len = None

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

                except (requests.exceptions.ChunkedEncodingError,
                        requests.exceptions.ConnectionError,
                        requests.exceptions.ReadTimeout,
                        TimeoutError) as _e:
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
                        if cr2:
                            resp_headers["Content-Range"] = cr2
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

    return StreamingResponse(streamer(), media_type=media_type,
                             headers=resp_headers, status_code=r.status_code)


# ═══════════════════════════════════════════════════════════════════════════════
# WARMING
# ═══════════════════════════════════════════════════════════════════════════════

def _warm_one(video_id: str) -> None:
    try:
        data = _get_or_extract(video_id)
        _probe_url(data["direct_url"])
    except Exception:
        pass


def _schedule_warm(ids: list[str]) -> None:
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


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/play")
def play_song(request: Request, id: str = Query(...), redir: int = Query(2)):
    try:
        data = get_audio_info_quick(id)
        audio_url = data["direct_url"]

        parsed_qs = urllib.parse.parse_qs(urllib.parse.urlsplit(audio_url).query)
        has_ip_param = "ip" in parsed_qs and parsed_qs["ip"] and parsed_qs["ip"][0]
        if redir == 1 and has_ip_param:
            redir = 2

        if redir == 2:
            range_header = request.headers.get("range")
            return _stream_from_url(audio_url, range_header)

        if redir == 1:
            return RedirectResponse(url=audio_url, status_code=307)

        return JSONResponse({"url": audio_url})

    except Exception as e:
        return JSONResponse(status_code=502, content={"error": "no_stream", "detail": str(e), "id": id})


@router.post("/prefetch")
def prefetch_songs(payload: dict = Body(...)):
    if not WARM_ENABLED:
        return {"ok": True, "scheduled": 0}
    raw_ids = payload.get("ids", []) or []
    ids = [str(i).strip() for i in raw_ids if i][:60]
    _schedule_warm(ids)
    return {"ok": True, "scheduled": min(len(ids), _WARM_BURST)}


@router.post("/warm")
def warm_ids(payload: dict = Body(...)):
    if not WARM_ENABLED:
        return {"ok": True, "scheduled": 0}
    ids = [str(i).strip() for i in (payload.get("ids") or []) if i]
    limit = int(payload.get("limit") or _WARM_BURST)
    _schedule_warm(ids[:limit])
    return {"ok": True, "scheduled": min(len(ids), limit)}