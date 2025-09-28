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
CACHE_TTL          = 30 * 60        # metadata genérica
URL_TTL            = 15 * 60        # fallback si no podemos leer expire
SEARCH_TTL         = 24 * 60 * 60   # cache 24h para búsquedas ATV por query (texto→videoId)
SEARCH_RESULT_TTL  = 10 * 60        # cache 10 min para /search (respuesta completa)
ARTIST_TTL         = 20 * 60        # cache 20 min para /artist/*
RECENT_TTL         = 2 * 60         # cache 2 min para /me/recent (con invalidación inmediata)
MAX_WORKERS        = 6              # tareas generales en background
WARM_MAX_WORKERS   = 3              # warming dedicado (no saturar)

# cache en memoria del proceso para URLs directas (videoId → direct_url)
_cache: dict[str, dict] = {}

# Cache para el mapeo OMV -> ATV (24h)
_FORCE_CACHE: dict[str, dict] = {}  # video_id -> {"atv": str, "ts": float}
_FORCE_TTL = 24 * 60 * 60

# Cache en memoria del proceso para /artist
_ARTIST_CACHE: dict[str, dict] = {}  # artist_id -> {"ts": float, "payload": dict}

# Cache para /me/recent por usuario + invalidación al loguear plays
_RECENT_CACHE: dict[str, dict] = {}  # key(user,limit) -> {"ts": float, "ver": int, "payload": dict}
_RECENT_VER: dict[str, int] = {}     # user_key -> version bump en cada play

# --- Cookies yt_dlp (una vez) ---
_COOKIES_INLINE = """# Netscape HTTP Cookie File
.youtube.com	TRUE	/	TRUE	0	SID	g.a0001ggw7Zqioddx-m5rtxTYOzJceCRWKt1gqYhOAyTM97RS-68PCVPM1EyuVixyN8eIeY8MjwACgYKAY4SARASFQHGX2MicEq2BkN7haZ8dGyKKLKbmxoVAUF8yKodte32gXvRe2VWu4lDK7Z_0076
.youtube.com	TRUE	/	TRUE	0	APISID	ScMc5qM3CynO_tXv/ANr1i1XLcgzRcfMKr
.youtube.com	TRUE	/	TRUE	0	LOGIN_INFO	AFmmF2swRQIhAP2bVZz0TWrixuq1UcjEeczVcW5uO5PJ5I7w6K_ES1jLAiB32CjBF8IIwfZ47QRMDJajMdZ4oQrxvxutLK-52WUA-w:QUQ3MjNmeEJ0VTBmejhzZWNKSTFjYVgyeGp1bTNwcVdGUXRsTkNodkIwVkpPTDdnQjN6S0ZPX0dLT2RndUVILUgtNVFKWVdLblVGbHdfeFduOXdac19JLTBKVEtFb2FVUGFRZGNCUnVrbzE4WlJOdW1ibDNrSzR5Vk1DdDZPaXp2ZHdfSmtNbUExVTZqdFlMdFJyR2pQVXlxdDhCcnhwdjRn
.youtube.com	TRUE	/	TRUE	0	YSC	huTQNsP2Cck
.youtube.com	TRUE	/	TRUE	0	PREF	f6=40000080&f7=4000&tz=America.Buenos_Aires&autoplay=true
.youtube.com	TRUE	/	TRUE	0	__Secure-3PSID	g.a0001ggw7Zqioddx-m5rtxTYOzJceCRWKt1gqYhOAyTM97RS-68PvCWsalX0VwkCvZwFn6skOAACgYKASMSARASFQHGX2MiDwwyXPN42b7gpLUty7LK-xoVAUF8yKqkTK-ycet6glaWqKO1ZT2l0076
.youtube.com	TRUE	/	TRUE	0	__Secure-3PSIDCC	AKEyXzVbY-KHj7ydwfZerlEtowAJwBgZGW-NhmIQlTql6n2sv86cE-chv9DuG8S1tFCxtDqq30l4
.youtube.com	TRUE	/	TRUE	0	VISITOR_INFO1_LIVE	wlUvqMj6iqI
.youtube.com	TRUE	/	TRUE	0	VISITOR_PRIVACY_METADATA	CgJBUhIEGgAgLA%3D%3D
.youtube.com	TRUE	/	TRUE	0	__Secure-3PAPISID	XHBTCAKBOTuQ_hnD/AvI5HYRLEv1bwYtUe
.youtube.com	TRUE	/	TRUE	0	SAPISID	XHBTCAKBOTuQ_hnD/AvI5HYRLEv1bwYtUe
.youtube.com	TRUE	/	TRUE	0	HSID	ANW6oYmuBCVHddSNq
.youtube.com	TRUE	/	TRUE	0	SSID	AiePXto1B1beosd0m
"""
_COOKIEFILE_PATH = os.path.join(tempfile.gettempdir(), "yt_inline_cookies.txt")
if not os.path.exists(_COOKIEFILE_PATH):
    with open(_COOKIEFILE_PATH, "w", encoding="utf-8") as _cf:
        _cf.write(_COOKIES_INLINE)

COOKIEFILE = "/root/musicappbackend/cookies.txt"

# --- HTTP session compartida ---
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "*/*", "Connection": "keep-alive"})
_adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=1)
_SESSION.mount("https://", _adapter)
_SESSION.mount("http://", _adapter)

# --- Executors ---
_BACKGROUND_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS)
_WARM_EXECUTOR       = ThreadPoolExecutor(max_workers=WARM_MAX_WORKERS)

# --- yt_dlp opts ---
def _ydl_for(client: str) -> yt_dlp.YoutubeDL:
    class _SilentLogger:
        def debug(self, msg):   pass
        def info(self, msg):    pass
        def warning(self, msg): pass
        def error(self, msg):   pass

    opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "logger": _SilentLogger(),
        "skip_download": True,
        "noplaylist": True,
        "extractor_args": {"youtube": {"player_client": [client]}},
        "cachedir": os.path.join(tempfile.gettempdir(), "yt_dlp_cache"),
        "socket_timeout": 5,
        "retries": 0,
        "extractor_retries": 0,
        "sleep_requests": 0.0,
        "source_address": "0.0.0.0",
        "http_headers": {"User-Agent": "Mozilla/5.0", "Accept-Language": "es-AR,es;q=0.9,en;q=0.8"},
        "cookiefile": COOKIEFILE,
    }
    return yt_dlp.YoutubeDL(opts)

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

def _extract_best_url(video_id: str):
    clients = ("web_music",)
    def pick_best_audio(info: dict) -> str | None:
        direct = info.get("url")
        if direct and direct.startswith("http"): return direct
        fmts = info.get("formats") or []
        audios = [f for f in fmts if (f.get("vcodec") in (None, "none")) and (f.get("acodec") not in (None, "none")) and f.get("url")]
        if not audios: return None
        def score(f):
            ext = (f.get("ext") or "").lower()
            ac  = (f.get("acodec") or "").lower()
            pr  = 2 if ("aac" in ac or "mp4a" in ac or ext == "m4a") else (1 if ("opus" in ac or ext == "webm" or "vorbis" in ac) else 0)
            br  = f.get("abr") or f.get("tbr") or 0
            return (pr, float(br))
        best = max(audios, key=score)
        return best.get("url")

    last_err = None
    for c in clients:
        try:
            ydl = _ydl_for(c)
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False, process=False)
            url = pick_best_audio(info)
            if url: return info, url, c
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError("no_audio_format" + (f": {last_err}" if last_err else ""))

# ---------- Helpers de performance (OMV→ATV + Warming) ----------
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
    if cached is not None: return (cached or {}).get("videoId")
    yt_local = InnerTube("WEB_REMIX")
    sresp = yt_local.search(q)
    songs = parse_search_songs(sresp, strict_atv=True)
    vid = songs[0]["videoId"] if songs else None
    set_cached(ck, {"videoId": vid}, SEARCH_TTL)
    return vid

# --- Mapeo OMV→ATV (bloqueante) ---
def _force_atv_id(video_id: str) -> str:
    now = time.time()
    ent = _FORCE_CACHE.get(video_id)
    if ent and (now - ent["ts"] < _FORCE_TTL):
        return ent["atv"] or video_id
    try:
        ydl = _ydl_for("web_music")
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False, process=False)
        title  = (info.get("track") or info.get("title") or "").strip()
        artist = (info.get("artist") or info.get("uploader") or "").strip()
        if (not info.get("track")) and " - " in title and not artist:
            artist, title = [p.strip() for p in title.split(" - ", 1)]
        q   = _normalize_query(artist, title)
        atv = _search_atv_first(q) if q else None
        _FORCE_CACHE[video_id] = {"atv": atv or video_id, "ts": now}
        return atv or video_id
    except Exception:
        _FORCE_CACHE[video_id] = {"atv": video_id, "ts": now}
        return video_id

# --- Variante QUICK: no bloquea; usa cache y agenda mapeo ---
def _maybe_force_cached(video_id: str) -> str:
    now = time.time()
    ent = _FORCE_CACHE.get(video_id)
    if ent and (now - ent["ts"] < _FORCE_TTL):
        return ent["atv"] or video_id
    # agenda el mapeo en background; devuelve el original YA
    try:
        _WARM_EXECUTOR.submit(_force_atv_id, video_id)
    except Exception:
        pass
    return video_id

# --- Core: obtener/cachar URL directa sin forzar mapeo ---
def _get_or_extract(video_id: str):
    now = time.time()
    cached = _cache.get(video_id)
    if cached and cached.get("direct_url"):
        ttl = cached.get("ttl", URL_TTL)
        if now - cached["ts"] < ttl:
            return cached
    info, direct_url, client = _extract_best_url(video_id)
    data = {
        "info": info,
        "direct_url": direct_url,
        "client": client,
        "ts": now,
        "ttl": _ttl_from_url(direct_url),
        "served": cached.get("served", 0) if cached else 0,
    }
    _cache[video_id] = data
    return data

# --- Rápido (no bloquea por mapeo) ---
def get_audio_info_quick(video_id: str):
    vid = _maybe_force_cached(video_id)   # puede devolver el original
    return _get_or_extract(vid)

# --- Completo (permite bloquear para mapear si hace falta) ---
def get_audio_info_blocking(video_id: str):
    vid = _force_atv_id(video_id)
    return _get_or_extract(vid)

def _probe_url(url: str) -> bool:
    headers = {"Range": "bytes=0-1"}
    try:
        r = _SESSION.get(url, headers=headers, stream=True, timeout=(2, 5), allow_redirects=True)
        ok = r.status_code in (200, 206)
        r.close()
        return ok
    except Exception:
        return False

def _stream_from_url(url: str, range_header: str | None) -> StreamingResponse:
    headers = {"Accept-Encoding": "identity", "Connection": "keep-alive"}
    headers["Range"] = range_header or "bytes=0-"
    r = _SESSION.get(url, headers=headers, stream=True, timeout=(5, 30), allow_redirects=True)
    resp_headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-store", "Connection": "keep-alive"}
    ct = r.headers.get("Content-Type");  media_type = ct if ct else "audio/webm"
    cl = r.headers.get("Content-Length");  cr = r.headers.get("Content-Range")
    if cl: resp_headers["Content-Length"] = cl
    if cr: resp_headers["Content-Range"]  = cr
    return StreamingResponse(r.iter_content(chunk_size=64 * 1024), media_type=media_type, headers=resp_headers, status_code=r.status_code)

# --------- WARMING 100% EN BACKGROUND ---------
def _warm_one(video_id: str) -> None:
    try:
        atv = _force_atv_id(video_id)       # acá sí mapeamos bloqueante (en background)
        data = _get_or_extract(atv)
        _probe_url(data["direct_url"])      # TTFB más bajo
    except Exception:
        pass

def _schedule_warm(ids: list[str]) -> None:
    if not ids: return
    uniq = [v for v in dict.fromkeys(ids) if v]
    for v in uniq[:50]:
        try:
            _WARM_EXECUTOR.submit(_warm_one, v)
        except Exception:
            pass

# --- AUDIO ENDPOINTS ---
@router.get("/play")
def play_song(
    request: Request,
    id: str = Query(..., description="YouTube video ID"),
    redir: int = Query(2, description="2=proxy stream (default), 1=redirect, 0=JSON url"),
):
    try:
        # 1) Camino rápido: NO bloquea por mapeo
        try:
            data = get_audio_info_quick(id)
            audio_url = data["direct_url"]
        except Exception as _fast_err:
            # 2) Fallback bloqueante si hizo falta
            try:
                data = get_audio_info_blocking(id)
                audio_url = data["direct_url"]
            except Exception:
                raise _fast_err

        print(f"[play] ➤ solicitando ID (quick) → {id}")

        # --- Anti-lag: si la URL viene con 'ip=' (ligada a la IP del server),
        # y el caller pidió redirect, forzamos PROXY igual.
        parsed_qs = urllib.parse.parse_qs(urllib.parse.urlsplit(audio_url).query)
        has_ip_param = "ip" in parsed_qs and parsed_qs["ip"] and parsed_qs["ip"][0]

        if redir == 1 and has_ip_param:
            print(f"[play] ⚠️ URL con ip={parsed_qs['ip'][0]} → forzamos PROXY")
            redir = 2

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
    """
    Agenda warming (sin bloquear). Devuelve al instante.
    """
    raw_ids = payload.get("ids", []) or []
    ids = [str(i).strip() for i in raw_ids if i][:50]
    _schedule_warm(ids)
    return {"ok": True, "scheduled": len(ids)}

# --- SEARCH ---
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
            _schedule_warm(list(dict.fromkeys(artist_ids + general_ids))[:20])
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
        _schedule_warm(list(dict.fromkeys(artist_ids + general_ids))[:20])
    except Exception as _e:
        print(f"[search][warm][WARN] {type(_e).__name__}: {_e}")

    return result

# --- ARTIST (cacheado + warm en background) ---
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
        _schedule_warm(ids[:12])
    except Exception as _e:
        print(f"[artist][warm][WARN] {_e}")

    return payload

@router.get("/artist")
def get_artist_q(id: str = Query(...)):
    return _artist_payload(id)

@router.get("/artist/{id}")
def get_artist_p(id: str = Path(...)):
    return _artist_payload(id)

# --- ALBUM (sin bloquear: warm async) ---
def _album_payload(album_id: str):
    yt = InnerTube("WEB_REMIX")
    response = yt.browse(album_id)

    tracks = parse_album_tracks(response)

    try:
        ids = [t.get("videoId") for t in tracks if t.get("videoId")]
        _schedule_warm(ids[:15])
    except Exception as _e:
        print(f"[album][warm][WARN] {_e}")

    payload = {"id": album_id, "info": parse_album_info(response), "tracks": tracks}
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

# --- Endpoint opcional para calentar desde el front ---
@router.post("/warm")
def warm_ids(payload: dict = Body(...)):
    ids = [str(i).strip() for i in (payload.get("ids") or []) if i]
    limit = int(payload.get("limit") or 20)
    _schedule_warm(ids[:limit])
    return {"ok": True, "scheduled": min(len(ids), limit)}

# --- NUEVOS: endpoints play logs + invalidación de recent ---
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

# --- LIKE / UNLIKE ---
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

# --- LIKES: lectura ---
def _db_for_request_simple(request: Request):
    jwt = (request.headers.get("Authorization") or "").replace("Bearer ", "")
    return db_as_user(jwt)

def _last_event_for_track(db, track_id: str):
    r = (db.table("user_activity")
           .select("event_type,occurred_at")
           .eq("entity_type", "track")
           .eq("entity_id", track_id)
           .in_("event_type", ["like", "unlike"])
           .order("occurred_at", desc=True)
           .limit(1)
           .execute())
    rows = r.data or []
    return rows[0]["event_type"] if rows else None

@router.get("/likes/tracks/{track_id}")
def is_track_liked(request: Request, track_id: str = Path(...)):
    try:
        db = _db_for_request_simple(request)
        last = _last_event_for_track(db, track_id)
        return {"track_id": track_id, "liked": (last == "like")}
    except Exception as e:
        print(f"[likes][single][ERROR] {e}")
        return JSONResponse(status_code=500, content={"ok": False, "error": "likes_check_failed"})

@router.post("/likes/tracks/check")
def are_tracks_liked(request: Request, payload: dict = Body(...)):
    raw_ids = payload.get("ids", [])
    ids = [str(i) for i in raw_ids if i][:200]
    if not ids: return {"liked": []}
    try:
        db = _db_for_request_simple(request)
        r = (db.table("user_activity")
               .select("entity_id, event_type, occurred_at")
               .eq("entity_type", "track")
               .in_("entity_id", ids)
               .in_("event_type", ["like", "unlike"])
               .order("entity_id", desc=False)
               .order("occurred_at", desc=True)
               .execute())
        rows = r.data or []
        last_by_id = {}
        for row in rows:
            tid = row["entity_id"]
            if tid in last_by_id: continue
            last_by_id[tid] = row["event_type"]
        liked = [tid for tid, ev in last_by_id.items() if ev == "like"]
        return {"liked": liked}
    except Exception as e:
        print(f"[likes][bulk][ERROR] {e}")
        return JSONResponse(status_code=500, content={"ok": False, "error": "likes_check_failed"})

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