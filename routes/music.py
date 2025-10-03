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
import threading  # ← NUEVO

from services.cache_service import get_cached, set_cached
from utils.search_parser import (
    parse_search_songs,
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
)
from utils.album_parser import parse_album_info, parse_album_tracks

from services.activity_service import try_log_activity_from_request
from services.supabase_service import db_as_user  # ← NUEVO

router = APIRouter()

# --- CONFIG ---
CACHE_TTL          = 30 * 60
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

# --- Cookies yt_dlp (SOLO TU RUTA) ---
COOKIEFILE = "/root/musicappbackend/cookies.txt"
if not os.path.exists(COOKIEFILE) or os.path.getsize(COOKIEFILE) == 0:
    raise RuntimeError(f"[music] COOKIEFILE no existe o está vacío: {COOKIEFILE}")

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
        # SOLO AUDIO: AAC (m4a) → Opus, jamás video
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

        # ↓ recorta validaciones extra de formatos (HEAD) en 2025.09.26
        "check_formats": False,

        "extractor_args": {
            "youtube": {
                "player_client": [client],                 # tv_embedded
                "player_skip": ["configs", "webpage"],     # NO "js"
                "max_comments": ["0"]
            }
        },

        "cachedir": os.path.join(tempfile.gettempdir(), "yt_dlp_cache"),
        "socket_timeout": 5,
        "retries": 0,
        "extractor_retries": 0,
        "sleep_requests": 0.0,
        "source_address": "0.0.0.0",
        "nocheckcertificate": True,
        "http_headers": {"User-Agent": "Mozilla/5.0", "Accept-Language": "es-AR,es;q=0.9,en;q=0.8"},
        "cookiefile": COOKIEFILE,
    }
    return yt_dlp.YoutubeDL(opts)

def _ydl_global() -> yt_dlp.YoutubeDL:
    """Devuelve una sola instancia global de YoutubeDL (protegida por lock)."""
    global _YDL_GLOBAL
    if _YDL_GLOBAL is None:
        _YDL_GLOBAL = _ydl_for("tv_embedded")  # mantenemos tv_embedded
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

def _normalize_query(artist_names: str, title: str) -> str:
    base = f"{artist_names} {title}".strip() if artist_names else (title or "").strip()
    if not base: return ""
    base = _norm_re_strip.sub("", base)
    base = _norm_re_noise.sub("", base)
    return re.sub(r"\s{2,}", " ", base).strip()

def _search_atv_first(q: str) -> str | None:
    if not q: return None
    ck = f"search_atv:{q.lower()}"
    cached = get_cached(ck)
    if cached is not None:
        return (cached or {}).get("videoId")

    # ↓ Reutiliza la sesión global de WEB_REMIX (keep-alive)
    sresp = _ytm().search(q)
    songs = parse_search_songs(sresp, strict_atv=True)
    vid = songs[0]["videoId"] if songs else None
    set_cached(ck, {"videoId": vid}, SEARCH_TTL)
    return vid

def _force_atv_from_info(orig_id: str, info: dict) -> str:
    """Deriva y cachea el ATV usando los metadatos ya extraídos."""
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
def _extract_best_url(video_id: str):
    """Extrae usando YDL global con lock; si falla/contiende, usa una instancia fresca."""
    def pick_best_audio(info: dict) -> str | None:
        fmts = info.get("formats") or []
        audios = [f for f in fmts
                  if (f.get("vcodec") in (None, "none"))
                  and (f.get("acodec") not in (None, "none"))
                  and f.get("url")]
        if not audios:
            u = info.get("url")
            return u if (u and u.startswith("http")) else None

        def score(f):
            ext = (f.get("ext") or "").lower()
            ac  = (f.get("acodec") or "").lower()
            pr  = 3 if ("mp4a" in ac or ext == "m4a") else (2 if "opus" in ac or ext == "webm" else 1)
            br  = float(f.get("abr") or f.get("tbr") or 0)
            asr = float(f.get("asr") or 0)
            return (pr, br, asr)

        return max(audios, key=score).get("url")

    info = None
    url = None

    # Intento 1: instancia global con lock (thread-safe)
    try:
        ydl = _ydl_global()
        with _YDL_LOCK:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}",
                                    download=False, process=False)
        url = pick_best_audio(info)
    except Exception:
        info = None
        url = None

    # Intento 2: fallback a instancia fresca (evita colgados si la global está ocupada/rota)
    if not url:
        ydl_fresh = _ydl_for("tv_embedded")  # mantenemos tv_embedded
        info = ydl_fresh.extract_info(f"https://www.youtube.com/watch?v={video_id}",
                                      download=False, process=False)
        url = pick_best_audio(info)

    if not url:
        raise RuntimeError("no_audio_format")

    return info, url, "tv_embedded"

def _get_or_extract(video_id: str, _force: bool = False):
    """
    Siempre fuerza ATV: extrae info del ID recibido, deriva ATV y si cambia re-extrae.
    Con Stale-While-Revalidate: si el cache venció pero la URL aún responde, devolvemos
    enseguida y refrescamos en background.
    """
    now = time.time()

    # cache directo
    ent = _cache.get(video_id)
    if ent and ent.get("direct_url"):
        fresh = (now - ent["ts"] < ent.get("ttl", URL_TTL))
        if fresh:
            return ent
        # SWR: si sigue respondiendo, devolvemos y refrescamos atrás
        if not _force:
            try:
                if _probe_url(ent["direct_url"]):
                    try:
                        _BACKGROUND_EXECUTOR.submit(_get_or_extract, video_id, True)
                    except Exception:
                        pass
                    return ent
            except Exception:
                pass

    # 1) extraigo info del ID que llegó (rápido, sin process)
    info1, url1, client1 = _extract_best_url(video_id)

    # 2) derivo ATV SIEMPRE con esos metadatos
    resolved_id = _FORCE_CACHE.get(video_id, {}).get("atv")
    if not resolved_id or (now - _FORCE_CACHE.get(video_id, {}).get("ts", 0) > _FORCE_TTL):
        resolved_id = _force_atv_from_info(video_id, info1)

    # 3) si cambió el ID, re-extraigo; si no, uso lo ya obtenido
    if resolved_id != video_id:
        try:
            info2, url2, client2 = _extract_best_url(resolved_id)
            info, direct_url, client = info2, url2, client2
        except Exception:
            info, direct_url, client = info1, url1, client1  # fallback
    else:
        info, direct_url, client = info1, url1, client1

    data = {
        "info": info,
        "direct_url": direct_url,
        "client": client,
        "ts": now,
        "ttl": _ttl_from_url(direct_url),
        "served": (ent or {}).get("served", 0),
    }
    # cacheo bajo el ID resuelto y también bajo el original como alias
    _cache[resolved_id] = data
    _cache[video_id] = data
    return data

# quick / blocking (ambos pasan por get_or_extract que ya fuerza ATV)
def get_audio_info_quick(video_id: str):
    return _get_or_extract(video_id)

def get_audio_info_blocking(video_id: str):
    return _get_or_extract(video_id)

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
    hdrs["Range"] = range_header or "bytes=0-"

    r = _SESSION_STREAM.get(url, headers=hdrs, stream=True,
                            timeout=(3, 20), allow_redirects=True)

    r.raw.decode_content = False

    resp_headers = {"Accept-Ranges": "bytes", "Connection": "keep-alive"}
    ct = r.headers.get("Content-Type")
    cr = r.headers.get("Content-Range")
    if cr:
        resp_headers["Content-Range"] = cr

    media_type = ct if ct else _guess_audio_media_type(url, None)

    CHUNK = 32 * 1024  # 32 KiB
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
        data = get_audio_info_quick(id)           # extracción + ATV
        t_ex1 = time.time()

        audio_url = data["direct_url"]
        print(f"[play] ➤ solicitando ID → {id}")

        # pre-probe opcional
        try:
            _probe_url(audio_url)
        except Exception:
            pass
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
            return _stream_from_url(audio_url, range_header)

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

    # (opcional) podrías también reusar _ytm() acá, pero lo dejado igual para no tocar tu flujo.
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
        "related": parse_related_artists(contents[7]) if len(contents) > 7 else [],
    }

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
def _album_tracks_force_songs(
    tracks: list[dict],
    album_name: str | None = None,
    year: str | int | None = None,
) -> list[dict]:
    """
    Forzar a canción SOLO cuando haga falta:
    - Si ya viene como ATV (song) con videoId -> NO tocar.
    - Si es OMV (video) o NO trae videoId -> buscar ATV.
      ***Primero artista+título; álbum/año solo como fallback***
    """
    out = []
    for t in tracks or []:
        vid = t.get("videoId")
        mvt = t.get("musicVideoType")  # de parse_album_tracks()

        if vid and mvt == "MUSIC_VIDEO_TYPE_ATV":
            out.append(t)
            continue

        title = (t.get("title") or "").strip()
        artists = t.get("artists") or []
        artist_names = " ".join([a.get("name", "") for a in artists if isinstance(a, dict)])

        q1 = _normalize_query(artist_names, title)
        atv = _search_atv_first(q1) if q1 else None

        if (not atv) and (album_name or year):
            q2 = " ".join([p for p in [q1, album_name, str(year) if year else None] if p]).strip()
            atv = _search_atv_first(q2) if q2 else None

        if atv and (not vid or mvt == "MUSIC_VIDEO_TYPE_OMV"):
            t["videoId"] = atv

        out.append(t)
    return out

def _dedupe_tracks_by_video(tracks: list[dict]) -> list[dict]:
    """Evita duplicados exactos (mismo videoId + title) preservando orden."""
    seen = set()
    out = []
    for t in tracks or []:
        key = (t.get("videoId"), t.get("title"))
        if t.get("videoId") and key in seen:
            continue
        if t.get("videoId"):
            seen.add(key)
        out.append(t)
    return out

def _album_payload(album_id: str):
    yt = InnerTube("WEB_REMIX")
    response = yt.browse(album_id)

    info = parse_album_info(response)
    album_name = (info or {}).get("title") or (info or {}).get("name")
    album_year = (info or {}).get("year")

    tracks = parse_album_tracks(response)
    tracks = _album_tracks_force_songs(tracks, album_name=album_name, year=album_year)
    tracks = _dedupe_tracks_by_video(tracks)

    try:
        ids = [t.get("videoId") for t in tracks if t.get("videoId")]
        _schedule_warm(ids[:_WARM_BURST])
    except Exception as _e:
        print(f"[album][warm][WARN] {_e}")

    payload = {"id": album_id, "info": info, "tracks": tracks}
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