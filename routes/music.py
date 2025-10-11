# routes/music.py
from fastapi import APIRouter, Query, Path, Body, Request
from fastapi.responses import StreamingResponse, JSONResponse, RedirectResponse
import time
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

from services.cache_service import get_cached, set_cached
from utils.search_parser import (
    parse_search_songs,
    parse_search_first_song_or_top,
    parse_artist_card_info,
    parse_artist_card_songs,
    parse_artist_card_albums,
    parse_search_albums_and_songs,
)
from utils.artist_parser import (
    parse_top_songs,
    parse_albums,
    parse_singles_eps,
    parse_related_artists,
    pick_related_artists_section
)
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
CACHE_TTL          = 30 * 60
EVENTS_TTL         = 30 * 60
URL_TTL            = 15 * 60
SEARCH_TTL         = 24 * 60 * 60
SEARCH_RESULT_TTL  = 10 * 60
ARTIST_TTL         = 20 * 60
RECENT_TTL         = 2 * 60
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
_RECENT_CACHE: dict[str, dict] = {}
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
def _ydl_for(client: str) -> yt_dlp.YoutubeDL:
    class _SilentLogger:
        def debug(self, msg):   pass
        def info(self, msg):    pass
        def warning(self, msg): pass
        def error(self, msg):   pass

    opts = {
        "format": "bestaudio[acodec^=mp4a]/bestaudio[ext=m4a]/bestaudio[acodec^=opus]/bestaudio/best",
        "format_sort": ["acodec:mp4a:m4a,opus", "abr", "asr", "size"],
        "prefer_free_formats": False,
        "youtube_include_dash_manifest": False,
        "youtube_include_hls_manifest": False,

        "quiet": True,
        "no_warnings": True,
        "logger": _SilentLogger(),
        "skip_download": True,
        "noplaylist": True,
        "check_formats": False,

        # ⚡ recorte de pasos de player para tv_embedded (menos requests)
        "extractor_args": {
            "youtube": {
                "player_client": [client],                  # seguimos usando tv_embedded
                "player_skip": ["configs","webpage","webpage_head", "watch"],
                "skip": ["hls", "dash", "translated_subs", "manifests"],
                "max_comments": ["0"],
            }
        },

        "cachedir": os.path.join(tempfile.gettempdir(), "yt_dlp_cache"),
        "socket_timeout": 3,
        "retries": 0,
        "extractor_retries": 0,
        "sleep_requests": 0.0,
        "source_address": "0.0.0.0",
        "nocheckcertificate": True,

        # 🧠 encabezados coherentes con tv_embedded (evita redirecciones extras)
        "http_headers": {
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
            "X-YouTube-Client-Name": "TVHTML5",
            "X-YouTube-Client-Version": "7.202.08",
        },

        "cookiefile": COOKIEFILE,
    }
    return yt_dlp.YoutubeDL(opts)

def _ydl_global() -> yt_dlp.YoutubeDL:
    global _YDL_GLOBAL
    if _YDL_GLOBAL is None:
        with _YDL_LOCK:
            if _YDL_GLOBAL is None:  # doble check por threads
                _YDL_GLOBAL = _ydl_for("tv_embedded")
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

def _events_cache_key_by_name(artist_name: str) -> str:
    s = " ".join((artist_name or "").strip().split()).casefold()
    return f"events:name:{s}"

def _events_cache_key_by_aid(aid: str) -> str:
    return f"events:aid:{(aid or '').strip()}"

def _normalize_query(artist_names: str, title: str) -> str:
    base = f"{artist_names} {title}".strip() if artist_names else (title or "").strip()
    if not base: return ""
    base = _norm_re_strip.sub("", base)
    base = _norm_re_noise.sub("", base)
    return re.sub(r"\s{2,}", " ", base).strip()

def _search_atv_first(q: str, *, dbg: str | None = None) -> str | None:
    """
    Usa parse_search_first_song_or_top (de utils/search_parser.py).
    Devuelve el videoId si el TopResult es ATV o si hay un ATV en el shelf 'Songs'.
    """
    def _log(tag: str, data: dict):
        try: print(f"[album][DBG] _search_atv_first: {tag}", data)
        except: pass

    if not q:
        _log("empty_query", {"dbg": dbg})
        return None

    ck = f"search_atv:{q.lower()}"
    cached = get_cached(ck)
    if cached is not None:
        vid = (cached or {}).get("videoId")
        _log("cache_hit", {"dbg": dbg, "q": q, "videoId": vid})
        return vid

    try:
        _log("search", {"dbg": dbg, "q": q})
        resp = _ytm().search(q)
        source, song = parse_search_first_song_or_top(resp)
        vid = song.get("videoId") if song else None
        _log("result", {
            "dbg": dbg, "q": q, "source": source,
            "title": (song or {}).get("title"),
            "musicVideoType": (song or {}).get("musicVideoType"),
            "videoId": vid
        })
        if vid:
            set_cached(ck, {"videoId": vid}, SEARCH_TTL)
            return vid
    except Exception as e:
        _log("search_exc", {"dbg": dbg, "q": q, "err": f"{type(e).__name__}: {e}"})

    # negativo corto para no clavar cache
    set_cached(ck, {"videoId": None}, 30)
    _log("no_result", {"dbg": dbg, "q": q})
    return None

def _force_atv_from_info(orig_id: str, info: dict) -> str:
    now = time.time()
    title  = (info.get("track") or info.get("title") or "").strip()
    artist = (info.get("artist") or info.get("uploader") or "").strip()
    if (not info.get("track")) and " - " in title and not artist:
        try:
            artist, title = [p.strip() for p in title.split(" - ", 1)]
        except Exception:
            pass
    q   = _normalize_query(artist, title)
    atv = _search_atv_first(q) if q else None
    _FORCE_CACHE[orig_id] = {"atv": atv or orig_id, "ts": now}
    return atv or orig_id

# ---------- Extracción ----------
def pick_best_audio(info: dict):
    """
    Elige el mejor audio entre los formatos del MISMO cliente (tv_embedded).
    Regla (parametrizable):
      - CODEC_FIRST: prioriza m4a/mp4a > opus/webm > resto
      - Si existe otro formato con kbps >= (mejor_m4a + BITRATE_DELTA_OVERRIDE),
        se elige ese por bitrate (override). Poné BITRATE_DELTA_OVERRIDE = 0.0
        si querés SIEMPRE el mayor kbps absoluto.
    Devuelve: (url, best_fmt, diag_dict)
    """
    # --- parámetros de regla ---
    CODEC_FIRST = True
    BITRATE_DELTA_OVERRIDE = 0.0  # bajalo a 0.0 para "siempre mayor kbps"

    fmts = info.get("formats") or []
    audios = [
        f for f in fmts
        if (f.get("vcodec") in (None, "none"))
        and (f.get("acodec") not in (None, "none"))
        and f.get("url")
    ]
    if not audios:
        u = info.get("url")
        return (u if (u and isinstance(u, str) and u.startswith("http")) else None,
                None, {"reason": "no_audio_formats"})

    # KBPS por itag conocido (aprox)
    ITAG_KBPS = {
        # AAC/M4A
        "139": 48, "140": 128, "141": 256,
        # Opus/WebM
        "249": 50, "250": 70, "251": 160,
        "171": 128, "172": 256,
    }

    def to_float(x, d=0.0):
        try:
            return float(x)
        except Exception:
            try:
                return float(str(x).replace(",", "."))
            except Exception:
                return d

    def codec_rank(f):
        ext = (f.get("ext") or "").lower()
        ac  = (f.get("acodec") or "").lower()
        if "mp4a" in ac or ext == "m4a":           return 3  # AAC/m4a
        if "opus" in ac or ext in ("webm","weba"): return 2  # Opus
        return 1

    def infer_kbps(f):
        v = f.get("abr") or f.get("tbr")
        if v is not None:
            return to_float(v, 0.0)
        itag = str(f.get("format_id") or f.get("format") or "")
        if itag in ITAG_KBPS:
            return ITAG_KBPS[itag]
        aq = (f.get("audio_quality") or f.get("quality") or "").upper()
        if "VERY" in aq and "HIGH" in aq: return 256
        if "HIGH" in aq:                 return 160
        if "MEDIUM" in aq:               return 128
        if "LOW" in aq:                  return 96
        return 0.0

    def samplerate(f):
        return to_float(f.get("asr") or f.get("audio_sample_rate"), 0.0)

    def fsize(f):
        return int((f.get("filesize") or f.get("filesize_approx") or 0) or 0)

    # 1) pick por ranking de códec + kbps + asr + tamaño
    def score_tuple(f):
        return (codec_rank(f), infer_kbps(f), samplerate(f), fsize(f))

    best_codec = max(audios, key=score_tuple)
    best_codec_kbps = infer_kbps(best_codec)

    # 2) override: si hay otro con kbps claramente mayor, preferirlo
    best_kbps_any = max(audios, key=lambda f: (infer_kbps(f), samplerate(f), fsize(f)))
    best_kbps_val = infer_kbps(best_kbps_any)

    reason = "codec_pref"
    winner = best_codec
    if CODEC_FIRST and (best_kbps_val >= best_codec_kbps + BITRATE_DELTA_OVERRIDE):
        winner = best_kbps_any
        reason = "bitrate_override"
    elif not CODEC_FIRST:
        winner = best_kbps_any
        reason = "kbps_only"

    # diag
    diag = {
        "reason": reason,
        "picked": {
            "itag": str(winner.get("format_id") or winner.get("format") or ""),
            "ext": (winner.get("ext") or "").lower(),
            "acodec": (winner.get("acodec") or "").lower(),
            "abr": to_float(winner.get("abr") or winner.get("tbr"), 0.0),
            "kbps_inferred": infer_kbps(winner),
            "asr": samplerate(winner),
            "filesize": fsize(winner),
        },
        "candidates": len(audios),
        "max_kbps_seen": max(infer_kbps(f) for f in audios) if audios else 0.0,
        "codec_first": CODEC_FIRST,
        "kbps_delta_override": BITRATE_DELTA_OVERRIDE,
    }

    return winner.get("url"), winner, diag


def _extract_best_url(video_id: str):
    """
    Extrae info con yt_dlp (tv_embedded), elige mejor audio con pick_best_audio,
    reintenta con un objeto "fresco" del MISMO cliente si falla, y loguea calidad.
    """
    info = None
    url = None
    best_fmt = None
    diag = None

    try:
        ydl = _ydl_global()
        with _YDL_LOCK:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}",
                                    download=False, process=False)
        url, best_fmt, diag = pick_best_audio(info)
    except Exception:
        info, url, best_fmt, diag = None, None, None, {"reason": "extract_failed_global"}

    if not url:
        # retry limpio del MISMO cliente (tv_embedded)
        ydl_fresh = _ydl_for("tv_embedded")
        info = ydl_fresh.extract_info(f"https://www.youtube.com/watch?v={video_id}",
                                      download=False, process=False)
        url, best_fmt, diag = pick_best_audio(info)

    if not url:
        raise RuntimeError("no_audio_format")

    # ---- LOG mínimo de calidad elegida ----
    try:
        print("[audio][pick]", {
            "id": video_id,
            "client": "tv_embedded",
            "reason": (diag or {}).get("reason"),
            "ext": (best_fmt or {}).get("ext"),
            "acodec": (best_fmt or {}).get("acodec"),
            "itag": (best_fmt or {}).get("format_id"),
            "abr": (best_fmt or {}).get("abr"),
            "tbr": (best_fmt or {}).get("tbr"),
            "kbps_inferred": (diag or {}).get("picked", {}).get("kbps_inferred"),
            "asr": (best_fmt or {}).get("asr"),
            "candidates": (diag or {}).get("candidates"),
            "max_kbps_seen": (diag or {}).get("max_kbps_seen"),
        })
    except Exception:
        pass

    return info, url, "tv_embedded"

def _get_or_extract(video_id: str, _force: bool = False):
    now = time.time()

    # 1) Cache caliente  ← DESACTIVADO
    # ent = _cache.get(video_id)
    # if ent and ent.get("direct_url"):
    #     fresh = (now - ent["ts"] < ent.get("ttl", URL_TTL))
    #     if fresh:
    #         return ent
    #     if not _force:
    #         try:
    #             if _probe_url(ent["direct_url"]):
    #                 try:
    #                     _BACKGROUND_EXECUTOR.submit(_get_or_extract, video_id, True)
    #                 except Exception:
    #                     pass
    #                 return ent
    #         except Exception:
    #             pass

    # 2) Intento primario...
    info1, url1, client1 = None, None, None
    forced_id = None
    try:
        info1, url1, client1 = _extract_best_url(video_id)
    except Exception:
        try:
            resolved_id = _FORCE_CACHE.get(video_id, {}).get("atv")
            if not resolved_id or (now - _FORCE_CACHE.get(video_id, {}).get("ts", 0) > _FORCE_TTL):
                resolved_id = _force_atv_from_info(video_id, {"track": "", "title": "", "artist": ""})
            info1, url1, client1 = _extract_best_url(resolved_id)
            forced_id = resolved_id
        except Exception:
            raise

    info, direct_url, client = info1, url1, client1

    data = {
        "info": info,
        "direct_url": direct_url,
        "client": client,
        "ts": now,
        "ttl": _ttl_from_url(direct_url),
        # "served": (ent or {}).get("served", 0),  # ← ent ya no existe
    }

    # ← ESCRITURA EN CACHÉ DESACTIVADA
    # _cache[video_id] = data
    # if forced_id and forced_id != video_id:
    #     _cache[forced_id] = data

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
        with _SESSION_STREAM.get(audio_url, stream=True, timeout=(3, 30), allow_redirects=True) as r:
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

def _stream_fullmirror(audio_url: str, cache_key: str, range_header: str | None) -> StreamingResponse:
    dst_path, tmp_path, meta_path = _cache_paths(cache_key)

    if os.path.exists(dst_path):
        media_type = "audio/mp4"
        try:
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as m:
                    mt = (m.read() or "").strip()
                    if mt: media_type = mt
        except Exception:
            pass
        return _serve_file_range(dst_path, range_header, media_type)

    if range_header and not range_header.strip().lower().startswith("bytes=0-"):
        try:
            _BACKGROUND_EXECUTOR.submit(_download_full_to_cache, audio_url, cache_key)
        except Exception:
            pass
        return _stream_from_url(audio_url, range_header)

    r = _SESSION_STREAM.get(audio_url, headers={"Accept-Encoding": "identity", "Connection": "keep-alive"},
                            stream=True, timeout=(3, 20), allow_redirects=True)
    r.raw.decode_content = False
    ct = r.headers.get("Content-Type") or "audio/mp4"
    try:
        with open(meta_path, "w", encoding="utf-8") as m:
            m.write(ct)
    except Exception:
        pass

    ftmp = open(tmp_path, "wb")
    CHUNK = 32 * 1024

    def body():
        try:
            while True:
                b = r.raw.read(CHUNK)
                if not b:
                    break
                try:
                    ftmp.write(b)
                except Exception:
                    pass
                yield b
        finally:
            try:
                r.close()
            except:
                pass
            def _finish():
                try:
                    with _SESSION_STREAM.get(audio_url, headers={"Accept-Encoding": "identity"},
                                             stream=True, timeout=(3, 30), allow_redirects=True) as r2:
                        for b2 in r2.iter_content(256 * 1024):
                            if not b2: break
                            try:
                                ftmp.write(b2)
                            except Exception:
                                pass
                except Exception:
                    pass
                finally:
                    try:
                        ftmp.close()
                    except Exception:
                        pass
                    try:
                        os.replace(tmp_path, dst_path)
                    except Exception:
                        try:
                            if os.path.exists(tmp_path): os.remove(tmp_path)
                        except Exception:
                            pass
            try:
                _BACKGROUND_EXECUTOR.submit(_finish)
            except Exception:
                try:
                    ftmp.close()
                    os.replace(tmp_path, dst_path)
                except Exception:
                    pass

    resp_headers = {"Accept-Ranges": "bytes", "Connection": "keep-alive"}
    cr = r.headers.get("Content-Range")
    if cr:
        resp_headers["Content-Range"] = cr

    return StreamingResponse(body(), media_type=ct, headers=resp_headers, status_code=r.status_code)

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
    hdrs = {"Accept-Encoding": "identity", "Connection": "keep-alive"}
    if range_header:
        hdrs["Range"] = range_header

    r = _SESSION_STREAM.get(url, headers=hdrs, stream=True,
                            timeout=(3, 20), allow_redirects=True)
    r.raw.decode_content = False

    resp_headers = {"Accept-Ranges": "bytes", "Connection": "keep-alive"}
    ct = r.headers.get("Content-Type")
    cr = r.headers.get("Content-Range")
    if cr:
        resp_headers["Content-Range"] = cr

    media_type = ct if ct else _guess_audio_media_type(url, None)

    CHUNK = 32 * 1024
    def body():
        try:
            while True:
                b = r.raw.read(CHUNK)
                if not b:
                    break
                yield b
        finally:
            try:
                r.close()
            except:
                pass

    return StreamingResponse(body(), media_type=media_type,
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

        """ try:
            _probe_url(audio_url)
        except Exception:
            pass """
        t_probe = time.time()

        parsed_qs = urllib.parse.parse_qs(urllib.parse.urlsplit(audio_url).query)
        has_ip_param = "ip" in parsed_qs and parsed_qs["ip"] and parsed_qs["ip"][0]
        if redir == 1 and has_ip_param:
            redir = 2

        print({
            "id": id,
            "extract_ms": int((t_ex1 - t_ex0)*1000),
            "preprobe_ms": int((t_probe - t_ex1)*1000),
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

    cached = get_cached(f"search:{q}")
    if cached:
        try_log_activity_from_request(request, event_type="search", entity_type="query", metadata={"query": q})
        try:
            artist_ids = [s.get("videoId") for s in (cached.get("artistSongs") or []) if s.get("videoId")]
            general_ids = [] if cached.get("artist") else [s.get("videoId") for s in (cached.get("search", {}).get("songs") or []) if s.get("videoId")]
            _schedule_warm(list(dict.fromkeys(artist_ids + general_ids))[:24])
        except Exception as _e:
            print(f"[search][cached][warm][WARN] {_e}")
        return cached

    yt = InnerTube("WEB_REMIX")
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
    set_cached(f"search:{q}", result, SEARCH_RESULT_TTL)

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
    ent = _ARTIST_CACHE.get(artist_id)
    now = time.time()
    if ent and (now - ent["ts"] < ARTIST_TTL):
        return ent["payload"]

    yt = InnerTube("WEB_REMIX")
    response = yt.browse(artist_id)

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

    # 1) Upcoming events (Ticketmaster): 10 “oficiales” por attractionId
    upcoming_events = []
    try:
        if name and name.strip():
            ev_ckey = _events_cache_key_by_name(name)
            ev_cached = get_cached(ev_ckey)

            if ev_cached and isinstance(ev_cached, dict):
                # hit: usar lo cacheado
                upcoming_events = (ev_cached.get("events") or [])[:10]
            else:
                # miss: pedir a Ticketmaster y cachear
                ev = fetch_upcoming_events_by_artist(name.strip(), limit=10, headliner_only=False)
                upcoming_events = (ev.get("events") or [])[:10]

                # cache por nombre normalizado (30m)
                set_cached(ev_ckey, ev, EVENTS_TTL)

                # si vino attractionId, duplicar cache por AID (útil después)
                aid = (ev or {}).get("attractionId")
                if aid:
                    set_cached(_events_cache_key_by_aid(aid), ev, EVENTS_TTL)
    except EventsError as _e:
        # clave faltante o artista no encontrado → no rompemos el payload
        print(f"[artist][events][WARN] {name}: {str(_e)}")
    except Exception as _e:
        print(f"[artist][events][ERR] {name}: {_e}")

    payload = {
        "header": {
            "name": name,
            "description": desc,
            "thumbnails": thumbs,
            "monthlyListeners": listeners,
        },
        "topSongs": parse_top_songs(contents[0]) if len(contents) > 0 else [],
        "albums": parse_albums(contents[1]) if len(contents) > 1 else [],
        "singles_eps": parse_singles_eps(contents[2]) if len(contents) > 2 else [],
        "related": parse_related_artists(rel_sec) if rel_sec else [],
        "upcomingEvents": upcoming_events,
    }

    payload["newReleases"] = list_new_releases_for_artist(artist_id, limit=8)

    _ARTIST_CACHE[artist_id] = {"ts": now, "payload": payload}

    try:
        ids = [t.get("videoId") for t in payload["topSongs"] if t.get("videoId")]
        _schedule_warm(ids[:_WARM_BURST])
    except Exception as _e:
        print(f"[artist][warm][WARN] {_e}")

    return payload

@router.get("/artist")
def get_artist_q(id: str = Query(...)):
    return _artist_payload(id)

@router.get("/artist/{id}")
def get_artist_p(id: str = Path(...)):
    return _artist_payload(id)

# ---------- ALBUM ----------

def _album_payload(album_id: str):
    yt = InnerTube("WEB_REMIX")
    response = yt.browse(album_id)

    info = parse_album_info(response)
    album_name = (info or {}).get("title") or (info or {}).get("name")
    album_year = (info or {}).get("year")
    try:
        print("[album][DBG] album_open", {"album_id": album_id, "name": album_name, "year": album_year})
    except:
        pass

    other_versions = parse_album_other_versions(response) or []
    releases_for_you = parse_album_releases_for_you(response) or []

    artist_id = (info or {}).get("artistId")
    more_from_artist = build_more_from_artist(artist_id, exclude_album_id=album_id, limit=10) if artist_id else []
    # ---------- UPCOMING EVENTS (mostrar 1 en álbum) ----------
    upcoming_events_one = []
    try:
        # 1) nombre del artista con múltiples fallbacks (algunos álbumes traen estructuras distintas)
        artist_name = (
            (info or {}).get("artistName")
            or ((info or {}).get("artists") or [{}])[0].get("name")
            or (info or {}).get("artist")
            or (info or {}).get("subtitle")  # a veces el parser mete "Artist • type"
        )
        # normaliza rápido si vino "Artist • ..." en subtitle
        if isinstance(artist_name, str) and " • " in artist_name:
            artist_name = artist_name.split(" • ", 1)[0].strip()

        # 2) si el ARTISTA ya fue abierto, reusar SU payload desde _ARTIST_CACHE (cero llamadas)
        #    => garantiza que TODOS los álbumes muestren evento tras abrir artista una vez
        if artist_id and artist_id in _ARTIST_CACHE:
            try:
                evs_from_artist = (_ARTIST_CACHE[artist_id]["payload"].get("upcomingEvents") or [])
                if evs_from_artist:
                    upcoming_events_one = evs_from_artist[:1]
            except Exception:
                pass

        # 3) si aún no tenemos evento, probamos cache por NOMBRE normalizado (30m)
        if not upcoming_events_one and artist_name:
            ev_ckey = _events_cache_key_by_name(artist_name)  # <- usa helper normalizado
            ev_cached = get_cached(ev_ckey)
            if ev_cached and isinstance(ev_cached, dict):
                upcoming_events_one = (ev_cached.get("events") or [])[:1]

        # 4) si tampoco hay cache (entraste por álbum primero), hacemos UNA llamada,
        #    y sembramos cache (por nombre y, si viene attractionId, también por aid)
        if not upcoming_events_one and artist_name:
            ev = fetch_upcoming_events_by_artist(artist_name.strip(), limit=1, headliner_only=False)
            upcoming_events_one = (ev or {}).get("events", [])[:1]

            # cache 30m por nombre normalizado
            set_cached(_events_cache_key_by_name(artist_name), ev, EVENTS_TTL)
            # y si vino attractionId, también por AID (opcional pero útil)
            aid = (ev or {}).get("attractionId")
            if aid:
                set_cached(_events_cache_key_by_aid(aid), ev, EVENTS_TTL)

    except EventsError as _e:
        print(f"[album][events][WARN] {album_id}: {str(_e)}")
    except Exception as _e:
        print(f"[album][events][ERR] {album_id}: {_e}")

    apid = (info or {}).get("audioPlaylistId")
    if not apid:
        print("[album][WARN] sin audioPlaylistId → tracks=[]")
        payload = {
            "id": album_id,
            "info": info,
            "tracks": [],
            "otherVersions": other_versions,
            "moreFromArtist": more_from_artist,
            "upcomingEvents": upcoming_events_one, 
            "releasesForYou": releases_for_you,
        }
        set_cached(f"album:{album_id}", payload, 30 * 60)
        return payload

    tracks = parse_tracks_from_audio_playlist(apid)

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
    set_cached(f"album:{album_id}", payload, 30 * 60)
    return payload

@router.get("/album")
def get_album_q(id: str = Query(...)):
    cached = get_cached(f"album:{id}")
    if cached: return cached
    return _album_payload(id)

@router.get("/album/{id}")
def get_album_p(id: str = Path(...)):
    cached = get_cached(f"album:{id}")
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

        user_key = _user_cache_key_from_request(request)
        ver = _RECENT_VER.get(user_key, 0)
        ckey = f"recent:{user_key}:{limit}"
        cent = _RECENT_CACHE.get(ckey)
        now = time.time()
        if cent and cent.get("ver") == ver and (now - cent.get("ts", 0) < RECENT_TTL):
            return cent["payload"]

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
            t = row.get("entity_type"); i = row.get("entity_id")
            if not t or not i: continue
            key = (t, i)
            if key in seen: continue
            seen.add(key)

            md  = row.get("metadata") or {}
            src = md.get("source") or {}

            name = _first(md.get("display_name"), md.get("name"), md.get("title"),
                          src.get("display_name"), src.get("name"), src.get("title"))
            thumb = _first(md.get("thumbnail_url"), md.get("thumbnail"),
                           src.get("thumbnail_url"), src.get("thumb"), src.get("thumbnail"))

            items.append({"type": t, "id": i, "occurred_at": row.get("occurred_at"),
                          "name": name, "thumbnail_url": thumb})
            if len(items) >= hard_limit: break

        payload = {"items": items}
        _RECENT_CACHE[ckey] = {"ts": now, "ver": ver, "payload": payload}
        return payload

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
        import time, random
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
    cached = get_cached(ck)
    if cached is not None:
        return cached

    yt = _ytmusic_client()
    b = _lyrics_browse_id_from_watch(yt, video_id)
    if not b:
        out = {"ok": False, "reason": "no_lyrics"}
        # cache corto negativo para no insistir
        set_cached(ck, out, 5 * 60)
        return out

    data = yt.get_lyrics(b) or {}
    out = {
        "ok": True,
        "lyrics": data.get("lyrics"),
        "source": data.get("source"),
    }
    set_cached(ck, out, _LYRICS_TTL)
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