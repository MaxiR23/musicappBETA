# routes/music.py
from fastapi import APIRouter, Query, Path, Body, Request
from fastapi.responses import StreamingResponse, JSONResponse, RedirectResponse
import time, random
import os
import re
import urllib.parse
import tempfile
from concurrent.futures import ThreadPoolExecutor

import requests
from requests.adapters import HTTPAdapter
import yt_dlp
from innertube import InnerTube
import threading 

from functools import lru_cache

import concurrent.futures as cf

from services.cache_service import get_cached_legacy, set_cached_legacy
from services.cache_config import CacheType

from utils.search_parser import (
    parse_search_songs,
    parse_search_first_song_or_top,
    parse_artist_card_info,
    parse_artist_card_songs,
    parse_artist_card_albums,
    parse_search_albums_and_songs,
)
from utils.artist_parser import (
    parse_top_songs_legacy,
    parse_top_songs_v2,
    parse_albums,
    parse_singles_eps,
    parse_related_artists,
    pick_related_artists_section,
)
from services.upcoming_releases_repo import get_upcoming_by_artist_id
from utils.album_parser import ( 
    parse_album_info,
    parse_album_tracks,
    parse_tracks_from_audio_playlist,
    parse_album_other_versions, 
    parse_album_releases_for_you,
    build_more_from_artist
)
from services.activity_service import try_log_activity_from_request
from services.supabase_service import db_as_user  

from services.feed_repo import list_new_releases_for_artist

from utils.events_upcoming import fetch_upcoming_events_by_artist, EventsError

router = APIRouter()

# --- CONFIG ---
MAX_WORKERS        = 8
WARM_MAX_WORKERS   = 10
WARM_ENABLED       = False

# --- yt_dlp global reusable (warm) ---
_YDL_GLOBAL: yt_dlp.YoutubeDL | None = None
_YDL_LOCK = threading.RLock()  # YoutubeDL no es thread-safe

# --- InnerTube global (WEB_REMIX) para evitar latencia por nueva sesión ---
_YTM_GLOBAL: InnerTube | None = None
_YTM_LOCK = threading.RLock()
def _ytm() -> InnerTube:
    global _YTM_GLOBAL
    with _YTM_LOCK:
        if _YTM_GLOBAL is None:
            _YTM_GLOBAL = InnerTube("WEB_REMIX")
        return _YTM_GLOBAL

# caches
_cache: dict[str, dict] = {}  # videoId -> {info, direct_url, ttl, ts, served}
_FORCE_CACHE: dict[str, dict] = {}  # OMV->ATV resolver: video_id -> {"atv": str, "ts": float}
_FORCE_TTL = 24 * 60 * 60
_ARTIST_CACHE: dict[str, dict] = {}
_RECENT_VER: dict[str, int] = {}
_WARM_INFLIGHT: dict[str, float] = {}
_WARM_BURST = 20
_WARM_DEDUP_TTL = 45

# --- Cookies yt_dlp (auto-resolución VPS / local) ---
POSSIBLE_COOKIE_PATHS = [
    "/root/musicappbackend/cookies.txt",  # VPS Linux
    os.path.join(os.getcwd(), "cookies.txt"),  # local carpeta backend/
    os.path.join(os.path.dirname(__file__), "..", "cookies.txt"),  # relativo
]

COOKIEFILE = next((p for p in POSSIBLE_COOKIE_PATHS if os.path.exists(p) and os.path.getsize(p) > 0), None)

if not COOKIEFILE:
    raise RuntimeError(
        f"[music] No se encontró cookies.txt válido en ninguna de las rutas:\n"
        + "\n".join(POSSIBLE_COOKIE_PATHS)
    )
else:
    print(f"[music] ✅ COOKIEFILE detectado: {COOKIEFILE}")

# --- HTTP sessions ---
_SESSION_SHORT = requests.Session()
_SESSION_SHORT.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "*/*", "Connection": "keep-alive"})
_SESSION_SHORT.mount("https://", HTTPAdapter(pool_connections=80, pool_maxsize=80, max_retries=0))
_SESSION_SHORT.mount("http://",  HTTPAdapter(pool_connections=80, pool_maxsize=80, max_retries=0))

_SESSION_STREAM = requests.Session()
_SESSION_STREAM.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "*/*", "Connection": "keep-alive"})
# ↓ ajustado para 1 vCPU/1GB RAM (menos FDs y memoria, mejor latencia)
_SESSION_STREAM.mount("https://", HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=0))
_SESSION_STREAM.mount("http://",  HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=0))

# --- Executors ---
_BACKGROUND_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS)
_WARM_EXECUTOR = None  # lazy init
def _get_warm_executor() -> ThreadPoolExecutor:
    global _WARM_EXECUTOR
    if _WARM_EXECUTOR is None:
        _WARM_EXECUTOR = ThreadPoolExecutor(max_workers=WARM_MAX_WORKERS)
    return _WARM_EXECUTOR

# --- yt_dlp opts ---
@lru_cache(maxsize=4)
def _ydl_for(client: str) -> yt_dlp.YoutubeDL:
    class _SilentLogger:
        def debug(self, msg):   pass
        def info(self, msg):    pass
        def warning(self, msg): pass
        def error(self, msg):   pass

    opts = {
        # Básicos
        "format": "bestaudio/best",
        "quiet": False,
        "no_warnings": False,
        #"logger": _SilentLogger(),
        "skip_download": True,
        "noplaylist": True,
        "noprogress": True,
        
        # Optimizaciones
        "geo_bypass": True,
        "no_check_certificates": True,
        "no_check_formats": True,
        "lazy_playlist": True,
        "ignoreerrors": False,
        "file_access_retries": 0,
        "ignore_no_formats_error": True,
        "skip_unavailable_fragments": True,
        
        # Extractor YouTube
        "extractor_args": {
            "youtube": {
                #"player_client": [client],
                #"player_skip": ["configs", "webpage", "initial_data"],
                "skip": ["hls", "dash", "translated_subs"],
                "player_client": ["android_vr"],
                "skip": ["hls", "dash"],
                "include_live_dash": False,
            }
        },
        
        # Timeouts agresivos
        "socket_timeout": 2.5,
        "retries": 0,
        "extractor_retries": 0,
        "fragment_retries": 0,
        "sleep_requests": 0,
        "sleep_interval": 0,
        "max_sleep_interval": 0,
        
        # HTTP
        "force_ipv4": True,
        "http_chunk_size": 2097152,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        },
        
        # Cache y cookies
        "cachedir": "/tmp/yt-dlp-cache",
        #"cookiefile": COOKIEFILE,
        "concurrent_fragment_downloads": 1,
    }
    return yt_dlp.YoutubeDL(opts)

def _ydl_global() -> yt_dlp.YoutubeDL:
    """
    Reutiliza instancia global. Lock SOLO para create/destroy.
    extract_info() es thread-safe desde yt-dlp 2023+.
    """
    global _YDL_GLOBAL
    
    # Crear instancia si no existe (con lock)
    if _YDL_GLOBAL is None:
        with _YDL_LOCK:
            if _YDL_GLOBAL is None:  # double-check
                _YDL_GLOBAL = _ydl_for("android_vr")
                _YDL_GLOBAL._request_count = 0
    
    # Recrear cada 1000 requests (sin lock en lectura)
    count = getattr(_YDL_GLOBAL, '_request_count', 0)
    if count > 1000:
        with _YDL_LOCK:
            # Re-check por si otro thread ya recreó
            if getattr(_YDL_GLOBAL, '_request_count', 0) > 1000:
                try:
                    if hasattr(_YDL_GLOBAL, 'close'):
                        _YDL_GLOBAL.close()
                except:
                    pass
                _YDL_GLOBAL = _ydl_for("android_vr")
                _YDL_GLOBAL._request_count = 0
    else:
        # Incrementar contador (thread-safe con GIL de Python)
        _YDL_GLOBAL._request_count = count + 1
    
    return _YDL_GLOBAL

def _ttl_from_url(u: str) -> int:
    try:
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)
        now = int(time.time())
        if "expire" in qs:
            exp = int(qs["expire"][0]); return max(60, min(90*60, exp - now - 120))
        if "x-goog-expires" in qs:
            ttl = int(qs["x-goog-expires"][0]); return max(60, min(90*60, ttl - 120))
    except Exception:
        pass
    return URL_TTL

# ---------- Helpers OMV→ATV ----------
_norm_re_strip = re.compile(r"(\(|\[).{0,80}?(\)|\])", re.IGNORECASE)
_norm_re_noise = re.compile(r"\b(official\s*video|video\s*oficial|video\s*clip|lyrics?|audio\s*only|HD|4K)\b", re.IGNORECASE)

# ---------- Extracción ----------
def pick_best_audio(info: dict):
    """
    Versión RÁPIDA: early-exit apenas encontramos formato aceptable.
    No analizamos TODOS los formatos, solo hasta encontrar uno bueno.
    """
    video_id = info.get("id", "unknown")  # ← AGREGÁ ESTO
    
    fmts = info.get("formats") or []
    audios = [
        f for f in fmts
        if (f.get("vcodec") in (None, "none"))
        and (f.get("acodec") not in (None, "none"))
        and f.get("url")
    ]
    
    if not audios:
        u = info.get("url")
        print(f"[pick_audio] {video_id}: ❌ no_audio_formats")  # ← AGREGÁ
        return (u if (u and isinstance(u, str) and u.startswith("http")) else None,
                None, {"reason": "no_audio_formats"})

    # Helper: inferir kbps del formato
    def infer_kbps(f):
        v = f.get("abr") or f.get("tbr")
        if v is not None:
            try:
                return float(v)
            except:
                pass
        
        itag = str(f.get("format_id") or "")
        ITAG_KBPS = {
            "139": 48, "140": 128, "141": 256,
            "249": 50, "250": 70, "251": 160,
        }
        return ITAG_KBPS.get(itag, 0.0)

    # ✅ android_vr: prioridad absoluta → OPUS itag 251
    for f in audios:
        itag = str(f.get("format_id") or "")
        ac   = (f.get("acodec") or "").lower()
        if itag == "251" and "opus" in ac and f.get("url"):
            print(f"[pick_audio] {video_id}: ✅ itag_251_opus ({infer_kbps(f)}kbps)")  # ← AGREGÁ
            return f.get("url"), f, {
                "reason": "itag_251_opus",
                "ext": f.get("ext"),
                "kbps": infer_kbps(f),
            }

    # Helper: ¿es suficientemente bueno?
    def is_good_enough(f):
        ext = (f.get("ext") or "").lower()
        ac = (f.get("acodec") or "").lower()
        kbps = infer_kbps(f)
        
        if ("mp4a" in ac or ext == "m4a") and kbps >= 128:
            return True
        if ("opus" in ac) and kbps >= 160:
            return True
        
        return False

    # ⚡ EARLY EXIT
    for f in audios:
        if is_good_enough(f):
            itag = f.get("format_id")
            ext = f.get("ext")
            kbps = infer_kbps(f)
            print(f"[pick_audio] {video_id}: ✅ early_exit itag={itag} {ext} {kbps}kbps")  # ← AGREGÁ
            return f.get("url"), f, {
                "reason": "early_exit",
                "ext": ext,
                "kbps": kbps,
            }

    # Fallback
    best = max(audios, key=lambda f: (
        3 if ("mp4a" in (f.get("acodec") or "").lower() or f.get("ext") == "m4a") else 1,
        infer_kbps(f)
    ))
    
    itag = best.get("format_id")
    ext = best.get("ext")
    kbps = infer_kbps(best)
    print(f"[pick_audio] {video_id}: ⚠️ fallback_best itag={itag} {ext} {kbps}kbps")  # ← AGREGÁ
    
    return best.get("url"), best, {
        "reason": "fallback_best",
        "kbps": kbps
    }

def _extract_best_url(video_id: str):
    timings = {}
    t0 = time.time()
    
    try:
        ydl = _ydl_global()
        timings["get_ydl"] = int((time.time() - t0) * 1000)
        
        t1 = time.time()
        # ⚡ CAMBIAR process=False a process=True para procesamiento inmediato
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}",
            download=False, 
            process=True  # ⚡ CAMBIO CRÍTICO
            )
        timings["extract_info"] = int((time.time() - t1) * 1000)
        
        t2 = time.time()
        url, best_fmt, diag = pick_best_audio(info)
        timings["pick_audio"] = int((time.time() - t2) * 1000)
        
        if not url:
            raise RuntimeError("no_audio_format")
        
        timings["total"] = int((time.time() - t0) * 1000)
        
        print(f"[TIMING] {video_id}: {timings}")
        
        return info, url, "android_vr"
        
    except Exception as e:
        print(f"[extract][ERROR] {video_id}: {type(e).__name__}: {e}")
        raise RuntimeError(f"extract_failed: {type(e).__name__}")

def _get_or_extract(video_id: str, _force: bool = False):
    """
    Extrae URL directa de audio. Con cache ultra-corta (60s) y sin fallbacks lentos.
    """
    now = time.time()

    # 1) Cache de 60s para evitar doble-extracción en re-clics
    if not _force:
        ent = _cache.get(video_id)
        if ent and ent.get("direct_url"):
            age = now - ent["ts"]
            if age < 600:
                return ent

    # 2) Extracción directa SIN buscar versiones ATV alternativasif ent and ent.get("direct_url"):
    try:
        info1, url1, client1 = _extract_best_url(video_id)
    except Exception as e:
        print(f"[get_or_extract][ERROR] {video_id}: {type(e).__name__}: {e}")
        raise

    # 3) Construir respuesta
    data = {
        "info": info1,
        "direct_url": url1,
        "client": client1,
        "ts": now,
        "ttl": _ttl_from_url(url1),
    }

    # 4) Guardar en cache por 60s
    _cache[video_id] = data
    
    return data

def get_audio_info_quick(video_id: str):
    return _get_or_extract(video_id)

def get_audio_info_blocking(video_id: str):
    return _get_or_extract(video_id)

# ---------- FS AUDIO CACHE (full file) ----------
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
                    if not chunk: break
                    f.write(chunk)
        os.replace(tmp_path, dst_path)
    except Exception:
        try:
            if os.path.exists(tmp_path): os.remove(tmp_path)
        except Exception:
            pass

# ---------- Networking ----------
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
    """
    Proxy de audio con:
      - Conexión al origen con Connection: close (evita sockets colgados)
      - Lectura por iter_content()
      - Manejo silencioso de desconexiones del cliente (BrokenPipe/GeneratorExit)
      - Reintento ÚNICO con Range "bytes=<enviado>-" si el origen corta a mitad
    """
    ORIGIN_CHUNK = 64 * 1024

    def open_req(extra_range: str | None):
        # Forzamos 'close' hacia el ORIGEN, mantenemos keep-alive hacia el CLIENTE
        hdrs = {"Accept-Encoding": "identity", "Connection": "close"}
        # Range del cliente → lo respetamos
        if range_header:
            hdrs["Range"] = range_header
        # Si pedimos reintento con offset, lo pisamos (tiene prioridad)
        if extra_range:
            hdrs["Range"] = extra_range

        r = _SESSION_STREAM.get(
            url,
            headers=hdrs,
            stream=True,
            timeout=(5, 120),          # subimos timeout de lectura
            allow_redirects=True,
        )
        r.raw.decode_content = False
        return r

    # --- 1) primer intento ---
    r = open_req(None)

    # Encabezados que devolveremos al CLIENTE
    resp_headers = {"Accept-Ranges": "bytes", "Connection": "keep-alive"}
    ct = r.headers.get("Content-Type")
    cr = r.headers.get("Content-Range")
    if cr:
        resp_headers["Content-Range"] = cr

    media_type = ct if ct else _guess_audio_media_type(url, None)

    # Total esperado (si lo sabemos) para calcular offset en reintento
    # Content-Range: "bytes start-end/total"
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
                    # Si terminó limpio, salimos
                    break

                except (requests.exceptions.ChunkedEncodingError,
                        requests.exceptions.ConnectionError,
                        requests.exceptions.ReadTimeout,
                        TimeoutError) as _e:
                    # Origen cortó. Intentamos UNA sola vez reanudar.
                    if tried_resume:
                        # Ya reintentamos: salir silenciosamente (evita 500)
                        break
                    tried_resume = True

                    # Calculamos nuevo Range. Si venía uno del cliente y ya enviamos 'sent',
                    # reanudamos desde 'sent' relativo al comienzo solicitado.
                    # Caso simple: no había Range → bytes=<sent>-
                    try:
                        if range_header and range_header.lower().startswith("bytes="):
                            # bytes=a-b  /  bytes=a-
                            # Tomamos 'a' como base_offset
                            base = range_header.split("=", 1)[1].split("-", 1)[0]
                            base_offset = int(base) if base else 0
                            new_start = base_offset + sent
                        else:
                            new_start = sent
                        # Cerrar request anterior y abrir otro desde new_start
                        try:
                            r.close()
                        except Exception:
                            pass
                        r = open_req(f"bytes={new_start}-")
                        # Actualizar Content-Range que verá el cliente a partir de ahora (opcional)
                        cr2 = r.headers.get("Content-Range")
                        if cr2:
                            resp_headers["Content-Range"] = cr2
                        continue
                    except Exception:
                        # Si no pudimos reanudar, cortamos sin romper la respuesta
                        break

        except (BrokenPipeError, ConnectionResetError, GeneratorExit):
            # El CLIENTE cortó: terminamos sin loguear error
            pass
        finally:
            try:
                r.close()
            except Exception:
                pass

    return StreamingResponse(streamer(), media_type=media_type,
                             headers=resp_headers, status_code=r.status_code)

# ---------- WARMING ----------
def _warm_one(video_id: str) -> None:
    try:
        data = _get_or_extract(video_id)
        _probe_url(data["direct_url"])
    except Exception:
        pass

def _schedule_warm(ids: list[str]) -> None:
    if not ids or not (globals().get("WARM_ENABLED", True)):
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

# ---------- AUDIO ENDPOINTS ----------
@router.get("/play")
def play_song(request: Request, id: str = Query(...), redir: int = Query(2)):
    t0 = time.time()
    try:
        t_ex0 = time.time()
        data = get_audio_info_quick(id)
        t_ex1 = time.time()

        audio_url = data["direct_url"]
        print(f"[play] ➤ solicitando ID → {id}")

        parsed_qs = urllib.parse.parse_qs(urllib.parse.urlsplit(audio_url).query)
        has_ip_param = "ip" in parsed_qs and parsed_qs["ip"] and parsed_qs["ip"][0]
        if redir == 1 and has_ip_param:
            redir = 2

        print({
            "id": id,
            "extract_ms": int((t_ex1 - t_ex0)*1000),
            "until_stream_setup_ms": int((time.time() - t0)*1000),
            "redir": redir,
        })

        if redir == 2:
            print(f"[play] 🛰️ PROXY stream → {audio_url[:80]}...")
            range_header = request.headers.get("range")
            # return _stream_fullmirror(audio_url, cache_key=id, range_header=range_header)  # ← caché (mirror) DESACTIVADO
            return _stream_from_url(audio_url, range_header)  # ← passthrough sin caché

        if redir == 1:
            print(f"[play] 🔀 307 → {audio_url[:80]}...")
            return RedirectResponse(url=audio_url, status_code=307)

        print(f"[play] 📦 JSON url")
        return JSONResponse({"url": audio_url})

    except Exception as e:
        print(f"[ERROR /play] ❌ id={id} → {str(e)}")
        return JSONResponse(status_code=502, content={"error": "no_stream", "detail": str(e), "id": id})

@router.post("/prefetch")
def prefetch_songs(payload: dict = Body(...)):
    if not WARM_ENABLED:
        return {"ok": True, "scheduled": 0}
    raw_ids = payload.get("ids", []) or []
    ids = [str(i).strip() for i in raw_ids if i][:60]
    _schedule_warm(ids)
    return {"ok": True, "scheduled": min(len(ids), _WARM_BURST)}

# ---------- SEARCH ----------
@router.get("/search")
def search_music(request: Request, q: str = Query(..., description="Texto a buscar")):
    auth_hdr = request.headers.get("Authorization", "")
    print(f"[search] Authorization len={len(auth_hdr)} sample={auth_hdr[:20]}...")
    mw_user = getattr(request.state, "user", None)
    print(f"[search] middleware.user => {mw_user}")

    cached = get_cached(CacheType.SEARCH, suffix=q.lower()[:100])
    if cached:
        try_log_activity_from_request(request, event_type="search", entity_type="query", metadata={"query": q})
        try:
            artist_ids = [s.get("videoId") for s in (cached.get("artistSongs") or []) if s.get("videoId")]
            general_ids = [] if cached.get("artist") else [s.get("videoId") for s in (cached.get("search", {}).get("songs") or []) if s.get("videoId")]
            _schedule_warm(list(dict.fromkeys(artist_ids + general_ids))[:24])
        except Exception as _e:
            print(f"[search][cached][warm][WARN] {_e}")
        return cached

    yt = _ytm()  
    response = yt.search(q)

    artist        = parse_artist_card_info(response)
    artist_songs  = parse_artist_card_songs(response, strict_atv=True)
    artist_albums = parse_artist_card_albums(response)

    if artist:
        general = parse_search_albums_and_songs(response, song_limit=0,  album_limit=10)
    else:
        general = parse_search_albums_and_songs(response, song_limit=10, album_limit=10)

    result = {
        "query": q,
        "artist": artist,
        "artistSongs": artist_songs,
        "artistAlbums": artist_albums,
        "search": general,
    }
    set_cached(CacheType.SEARCH, result, suffix=q.lower()[:100])

    try_log_activity_from_request(request, event_type="search", entity_type="query", metadata={"query": q})

    try:
        artist_ids = [s.get("videoId") for s in (artist_songs or []) if s.get("videoId")]
        general_ids = [] if artist else [s.get("videoId") for s in (general.get("songs") or []) if s.get("videoId")]
        _schedule_warm(list(dict.fromkeys(artist_ids + general_ids))[:24])
    except Exception as _e:
        print(f"[search][warm][WARN] {type(_e).__name__}: {_e}")

    return result

# ---------- ARTIST ----------
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
    listeners = header.get("monthlyListenerCount", {}).get("runs", [{}])[0].get("text")

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
        if name and name.strip():
            ev_cached = get_cached(CacheType.EVENTS, suffix=name.lower())
            if isinstance(ev_cached, dict):
                upcoming_events = (ev_cached.get("events") or [])[:10]
            else:
                _schedule_events_refresh_by_name(name.strip())
    except Exception as _e:
        print(f"[artist][events][WARN] {name}: {_e}")

    # 5) Albums - parsers manuales + hasMore desde ytmusicapi
    albums_filtered = (parse_albums(contents[1]) if len(contents) > 1 else [])[:10]
    albums_section = artist_data.get("albums", {})
    has_more_albums = albums_section.get("browseId") is not None and len(albums_section.get("results", [])) >= 10

    # 6) Singles - parsers manuales + hasMore desde ytmusicapi
    singles_filtered = (parse_singles_eps(contents[2]) if len(contents) > 2 else [])[:10]
    singles_section = artist_data.get("singles", {})
    has_more_singles = singles_section.get("browseId") is not None and len(singles_section.get("results", [])) >= 10

    # 7) payload
    payload = {
        "header": {
            "name": name,
            "description": desc,
            "thumbnails": thumbs,
            "monthlyListeners": listeners,
        },
        "topSongs": parse_top_songs_v2(artist_data, yt),
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

    # 9) upcoming albums 
    try:
        payload["upcoming_album"] = get_upcoming_by_artist_id(artist_id) or None
    except Exception as _e:
        print(f"[artist][upcoming_album][WARN] {artist_id}: {_e}")
        payload["upcoming_album"] = None    

    # 9) cache y warm
    _ARTIST_CACHE[artist_id] = {"ts": time.time(), "payload": payload}
    set_cached(CacheType.ARTIST, payload, suffix=artist_id)
    try:
        ids = [t.get("id") for t in payload["topSongs"] if t.get("id")]
        _schedule_warm(ids[:_WARM_BURST])
    except Exception as _e:
        print(f"[artist][warm][WARN] {_e}")

    return payload

@router.get("/artist")
def get_artist_q(id: str = Query(...)):
    cached = get_cached(CacheType.ARTIST, suffix=id)       
    if cached: return cached 
    return _artist_payload(id)

@router.get("/artist/{id}")
def get_artist_p(id: str = Path(...)):
    cached = get_cached(CacheType.ARTIST, suffix=id)       
    if cached: return cached     
    return _artist_payload(id)

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

# ---------- ALBUM ----------
def _album_payload(album_id: str):
    # 0) usar cliente global (evita latencia de nueva sesión)
    yt = _ytm()  # InnerTube("WEB_REMIX") → _ytm() global reuse

    # 1) browse una sola vez
    response = yt.browse(album_id)

    # 2) parsers rápidos del mismo response
    info = parse_album_info(response)
    album_name = (info or {}).get("title") or (info or {}).get("name")
    album_year = (info or {}).get("year")
    try:
        print("[album][DBG] album_open", {"album_id": album_id, "name": album_name, "year": album_year})
    except:
        pass

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
            "moreFromArtist": [],   # sin artistId no hay más
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
        tracks = fut_tracks.result(timeout=2.5)  # ⚡ corta latencia en fríos/lentos
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

@router.get("/album")
def get_album_q(id: str = Query(...)):
    cached = get_cached(CacheType.ALBUM, suffix=id)
    if cached: return cached
    return _album_payload(id)

@router.get("/album/{id}")
def get_album_p(id: str = Path(...)):
    cached = get_cached(CacheType.ALBUM, suffix=id)
    if cached: return cached
    return _album_payload(id)

# ---------- WARM endpoint ----------
@router.post("/warm")
def warm_ids(payload: dict = Body(...)):
    if not WARM_ENABLED:
        return {"ok": True, "scheduled": 0}
    ids = [str(i).strip() for i in (payload.get("ids") or []) if i]
    limit = int(payload.get("limit") or _WARM_BURST)
    _schedule_warm(ids[:limit])
    return {"ok": True, "scheduled": min(len(ids), limit)}

# ---------- Plays / Likes / Recent ----------
def _user_cache_key_from_request(request: Request) -> str:
    u = getattr(request.state, "user", None) or {}
    uid = u.get("id") if isinstance(u, dict) else None
    if uid: return f"user:{uid}"
    jwt = (request.headers.get("Authorization") or "").replace("Bearer ", "").strip()
    return f"jwt:{hash(jwt) if jwt else 'anon'}"

def _bump_recent_version(user_key: str):
    _RECENT_VER[user_key] = (_RECENT_VER.get(user_key, 0) + 1) % 1_000_000

@router.post("/plays/albums/{album_id}")
def log_play_album(request: Request, album_id: str = Path(...), body: dict | None = Body(None)):
    b = body or {}
    meta = {}
    if b.get("source"): meta["source"] = b["source"]
    dn = b.get("display_name") or b.get("name") or b.get("title")
    th = b.get("thumbnail_url") or b.get("thumbnail")
    if dn: meta["display_name"] = dn
    if th: meta["thumbnail_url"] = th

    try_log_activity_from_request(request, event_type="play", entity_type="album", entity_id=album_id,
                                  context_type="album", context_id=album_id, metadata=meta or None)
    try: _bump_recent_version(_user_cache_key_from_request(request))
    except Exception: pass
    return {"ok": True}

@router.post("/plays/artists/{artist_id}")
def log_play_artist(request: Request, artist_id: str = Path(...), body: dict | None = Body(None)):
    b = body or {}
    meta = {}
    if b.get("source"): meta["source"] = b["source"]
    dn = b.get("display_name") or b.get("name") or b.get("title")
    th = b.get("thumbnail_url") or b.get("thumbnail")
    if dn: meta["display_name"] = dn
    if th: meta["thumbnail_url"] = th

    try_log_activity_from_request(request, event_type="play", entity_type="artist", entity_id=artist_id,
                                  context_type="artist", context_id=artist_id, metadata=meta or None)
    try: _bump_recent_version(_user_cache_key_from_request(request))
    except Exception: pass
    return {"ok": True}

@router.post("/likes/tracks/{track_id}")
def like_track(request: Request, track_id: str = Path(...), body: dict | None = Body(None)):
    source = (body or {}).get("source")
    try_log_activity_from_request(request, event_type="like", entity_type="track", entity_id=track_id,
                                  context_type="track", context_id=track_id,
                                  metadata={"source": source} if source else None)
    return {"ok": True}

@router.post("/unlikes/tracks/{track_id}")
def unlike_track(request: Request, track_id: str = Path(...), body: dict | None = Body(None)):
    source = (body or {}).get("source")
    try_log_activity_from_request(request, event_type="unlike", entity_type="track", entity_id=track_id,
                                  context_type="track", context_id=track_id,
                                  metadata={"source": source} if source else None)
    return {"ok": True}

@router.post("/likes/albums/{album_id}")
def like_album(request: Request, album_id: str = Path(...), body: dict | None = Body(None)):
    source = (body or {}).get("source")
    try_log_activity_from_request(request, event_type="like", entity_type="album", entity_id=album_id,
                                  context_type="album", context_id=album_id,
                                  metadata={"source": source} if source else None)
    return {"ok": True}

@router.post("/unlikes/albums/{album_id}")
def unlike_album(request: Request, album_id: str = Path(...), body: dict | None = Body(None)):
    source = (body or {}).get("source")
    try_log_activity_from_request(request, event_type="unlike", entity_type="album", entity_id=album_id,
                                  context_type="album", context_id=album_id,
                                  metadata={"source": source} if source else None)
    return {"ok": True}

@router.post("/likes/artists/{artist_id}")
def like_artist(request: Request, artist_id: str = Path(...), body: dict | None = Body(None)):
    source = (body or {}).get("source")
    try_log_activity_from_request(request, event_type="like", entity_type="artist", entity_id=artist_id,
                                  context_type="artist", context_id=artist_id,
                                  metadata={"source": source} if source else None)
    return {"ok": True}

@router.post("/unlikes/artists/{artist_id}")
def unlike_artist(request: Request, artist_id: str = Path(...), body: dict | None = Body(None)):
    source = (body or {}).get("source")
    try_log_activity_from_request(request, event_type="unlike", entity_type="artist", entity_id=artist_id,
                                  context_type="artist", context_id=artist_id,
                                  metadata={"source": source} if source else None)
    return {"ok": True}

@router.post("/likes/playlists/{playlist_id}")
def like_playlist(request: Request, playlist_id: str = Path(...), body: dict | None = Body(None)):
    source = (body or {}).get("source")
    try_log_activity_from_request(request, event_type="like", entity_type="playlist", entity_id=playlist_id,
                                  context_type="playlist", context_id=playlist_id,
                                  metadata={"source": source} if source else None)
    return {"ok": True}

@router.post("/unlikes/playlists/{playlist_id}")
def unlike_playlist(request: Request, playlist_id: str = Path(...), body: dict | None = Body(None)):
    source = (body or {}).get("source")
    try_log_activity_from_request(request, event_type="unlike", entity_type="playlist", entity_id=playlist_id,
                                  context_type="playlist", context_id=playlist_id,
                                  metadata={"source": source} if source else None)
    return {"ok": True}

# --- utils ---
def _first(*vals):
    for v in vals:
        if v not in (None, "", [], {}):
            return v
    return None

# --- ME / RECENT ---
@router.get("/me/recent")
def get_recent_plays(request: Request, limit: int = 20):
    try:
        jwt = (request.headers.get("Authorization") or "").replace("Bearer ", "").strip()
        if not jwt:
            return JSONResponse(status_code=401, content={"ok": False, "error": "unauthorized"})

        db = db_as_user(jwt)

        # Sin caché - siempre datos frescos
        hard_limit  = max(1, min(100, int(limit)))
        fetch_limit = min(3 * hard_limit, 150)
        
        resp = (db.table("user_activity")
                  .select("entity_type, entity_id, occurred_at, metadata")
                  .eq("event_type", "play")
                  .in_("entity_type", ["album", "artist"])
                  .order("occurred_at", desc=True)
                  .limit(fetch_limit)
                  .execute())
        rows = resp.data or []

        seen = set()
        items = []
        for row in rows:
            t = row.get("entity_type")
            i = row.get("entity_id")
            if not t or not i:
                continue
            
            key = (t, i)
            if key in seen:
                continue
            seen.add(key)

            md = row.get("metadata") or {}
            src = md.get("source") or {}

            name = _first(
                md.get("display_name"), md.get("name"), md.get("title"),
                src.get("display_name"), src.get("name"), src.get("title")
            )
            thumb = _first(
                md.get("thumbnail_url"), md.get("thumbnail"),
                src.get("thumbnail_url"), src.get("thumb"), src.get("thumbnail")
            )

            items.append({
                "type": t,
                "id": i,
                "occurred_at": row.get("occurred_at"),
                "name": name,
                "thumbnail_url": thumb
            })
            
            if len(items) >= hard_limit:
                break

        return {"items": items}

    except Exception as e:
        print(f"[recent][ERROR] {e}")
        return JSONResponse(status_code=500, content={"ok": False, "error": "recent_failed"})
    
@router.post("/playlists/{playlist_id}/move-track")
def move_playlist_track(
    request: Request,
    playlist_id: str = Path(...),
    body: dict = Body(...),
):
    # ── auth ─────────────────────────────────────────────
    auth = (request.headers.get("Authorization") or "").strip()
    jwt  = auth.replace("Bearer ", "").strip()
    if not jwt:
        return JSONResponse(status_code=401, content={"ok": False, "error": "unauthorized"})

    # ── body ─────────────────────────────────────────────
    old_position = body.get("old_position")
    new_position = body.get("new_position")
    if not isinstance(old_position, int) or not isinstance(new_position, int) \
       or old_position < 1 or new_position < 1:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid_params"})

    try:
        db = db_as_user(jwt)

        # snapshot pre (para log y fallback visual)
        pre = (
            db.table("playlist_tracks")
              .select("id,position")
              .eq("playlist_id", playlist_id)
              .order("position", desc=False)
              .execute()
        ).data or []
        print(f"[reorder][pre] n={len(pre)} first20={pre[:20]}")

        # fila a mover por position exacta
        row = (
            db.table("playlist_tracks")
              .select("id,position")
              .eq("playlist_id", playlist_id)
              .eq("position", old_position)
              .limit(1)
              .execute()
        )

        # ⚠️ fallback si hay huecos: usar ordinal del snapshot (1-based)
        if not row.data:
            if 1 <= old_position <= len(pre):
                track_row_id = pre[old_position - 1]["id"]
                print(f"[reorder] fallback ordinal -> id={track_row_id} (old_position={old_position})")
            else:
                return JSONResponse(status_code=404, content={"ok": False, "error": "track_not_found"})
        else:
            track_row_id = row.data[0]["id"]

        # clamp destino usando snapshot (consistente con UI)
        total = len(pre)
        if new_position > total: new_position = total
        if new_position < 1:     new_position = 1
        if new_position == old_position:
            # devolver orden actual igual para refrescar si el front quiere
            ordered_now = (
                db.table("playlist_tracks")
                  .select("id,track_id,position")
                  .eq("playlist_id", playlist_id)
                  .order("position", desc=False)
                  .execute()
            ).data or []
            return {"ok": True, "noop": True, "order": [
                {"internalId": r["id"], "trackId": r["track_id"], "position": r["position"]}
                for r in ordered_now
            ]}

        print(f"[reorder] move old={old_position} -> new={new_position} id={track_row_id}")

        # ── SENTINEL SEGURO (int32 negativo) + reintento ──
        base = int(time.time()) ^ random.randint(1, 1_000_000)
        candidate = - (1 + (abs(base) % 999_999))          # rango: [-999999, -1]
        parked = False
        for attempt in range(6):  # intenta hasta 6 valores distintos
            try:
                (
                    db.table("playlist_tracks")
                      .update({"position": candidate})
                      .eq("id", track_row_id)
                      .execute()
                )
                parked = True
                print(f"[reorder] parked id={track_row_id} -> {candidate} (attempt={attempt})")
                break
            except Exception as e:
                candidate -= 1
                if candidate < -2_000_000:
                    candidate = -1
                print(f"[reorder] park retry due to {type(e).__name__}: {e}")
        if not parked:
            return JSONResponse(status_code=500, content={"ok": False, "error": "sentinel_failed"})

        # ── SHIFTS UNITARIOS EN ORDEN SEGURO ──
        if new_position < old_position:
            # subir: [new, old-1] => +1 (descendente)
            for pos in range(old_position - 1, new_position - 1, -1):
                resp = (
                    db.table("playlist_tracks")
                      .update({"position": pos + 1})
                      .eq("playlist_id", playlist_id)
                      .eq("position", pos)
                      .execute()
                )
                print(f"[reorder] shift_up {pos} -> {pos+1} rows={len(resp.data or [])}")
        else:
            # bajar: [old+1, new] => -1 (ascendente)
            for pos in range(old_position + 1, new_position + 1):
                resp = (
                    db.table("playlist_tracks")
                      .update({"position": pos - 1})
                      .eq("playlist_id", playlist_id)
                      .eq("position", pos)
                      .execute()
                )
                print(f"[reorder] shift_down {pos} -> {pos-1} rows={len(resp.data or [])}")

        # ── colocar el track movido en su destino ──
        fin = (
            db.table("playlist_tracks")
              .update({"position": new_position})
              .eq("id", track_row_id)
              .execute()
        )
        print(f"[reorder] set_final id={track_row_id} -> {new_position} ok_rows={len(fin.data or [])}")

        # snapshot post para verificar y devolver orden resuelto
        post = (
            db.table("playlist_tracks")
              .select("id,position")
              .eq("playlist_id", playlist_id)
              .order("position", desc=False)
              .execute()
        ).data or []
        print(f"[reorder][post] n={len(post)} first20={post[:20]}")

        # verificación 1..N sin huecos/duplicados
        gaps, dups, seen = [], [], set()
        expected = 1
        for r in post:
            p = int(r["position"])
            if p in seen: dups.append(p)
            seen.add(p)
            if p != expected:
                gaps.append({"expected": expected, "found": p})
                expected = p
            expected += 1
        if dups or gaps:
            print(f"[reorder][WARN] dups={dups} gaps={gaps}")

        # orden completo (para que el front lo pinte sin esperar otro fetch)
        ordered = (
            db.table("playlist_tracks")
              .select("id,track_id,position")
              .eq("playlist_id", playlist_id)
              .order("position", desc=False)
              .execute()
        ).data or []

        return {
            "ok": True,
            "order": [{"internalId": r["id"], "trackId": r["track_id"], "position": r["position"]} for r in ordered],
            "positions_sample": [r["position"] for r in post[:30]],
            "dups": dups,
            "gaps": gaps
        }

    except Exception as e:
        print(f"[reorder][EXC] {type(e).__name__}: {e}")
        return JSONResponse(status_code=500, content={
            "ok": False,
            "error": "move_failed",
            "detail": f"{type(e).__name__}: {e}"
        })
    
# ---------- LYRICS (YouTube Music) ----------
_LYRICS_TTL = 12 * 60 * 60  # 12h

def _ytmusic_client():
    # import lazy para no cargar ytmusicapi si no se usa
    from ytmusicapi import YTMusic
    return YTMusic()

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
    No toca /play ni rutas existentes.
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

# ---------- RELATED (YouTube Music) ----------
_RELATED_TTL = 12 * 60 * 60  # 12h

# Secciones a excluir
_EXCLUDED_RELATED_SECTIONS = {
    "Recommended playlists",
    "Other performances",
}

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
        set_cached(ck, out, 1 * 60)
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
    
def _normalize_thumbnail(track: dict) -> dict:
    """Extrae la mejor thumbnail y la pone como string"""
    thumbs = track.get("thumbnail") or track.get("thumbnails") or []
    best_url = thumbs[-1].get("url") if thumbs else None
    return {**track, "thumbnail": best_url}

# ---------- UP NEXT / QUEUE (YouTube Music) ----------
_UPNEXT_TTL = 6 * 60 * 60  # 6h (más corto porque es dinámico)

def _get_track_upnext_backend(video_id: str) -> dict:
    ck = f"upnext:{video_id}"
    cached = get_cached_legacy(ck)
    if cached is not None:
        return cached

    yt = _ytmusic_client()
    
    try:
        # 1) Detalles de la canción actual
        song_raw = yt.get_song(video_id) or {}
        video_details = song_raw.get("videoDetails") or {}
        
        # 2) Play Next (watch playlist)
        watch = yt.get_watch_playlist(videoId=video_id) or {}
        tracks = watch.get("tracks") or []
        
        if not tracks:
            out = {"ok": False, "reason": "no_tracks"}
            set_cached_legacy(ck, out, 5 * 60)
            return out
        
        out = {
            "ok": True,
            "current": {
                "videoId": video_details.get("videoId"),
                "title": video_details.get("title"),
                "author": video_details.get("author"),
                "lengthSeconds": video_details.get("lengthSeconds"),
            },
            "upNext": [_normalize_thumbnail(t) for t in tracks],  # Ya viene formateado por ytmusicapi
            "autoplay": watch.get("autoplay")  # Por si querés saber si tiene autoplay
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
    Devuelve la cola de reproducción (up next) para un videoId.
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