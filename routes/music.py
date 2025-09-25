# routes/music.py
from fastapi import APIRouter, Query, Path, Body, Request
from fastapi.responses import StreamingResponse, JSONResponse, RedirectResponse
import time
import os
import re
import urllib.parse
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
import yt_dlp
from innertube import InnerTube

from services.cache_service import get_cached, set_cached
from utils.search_parser import parse_search_songs, parse_search_artists
from utils.artist_parser import (
    parse_top_songs,
    parse_albums,
    parse_singles_eps,
    parse_related_artists,
)
from utils.album_parser import parse_album_info, parse_album_tracks

router = APIRouter()

# --- CONFIG ---
CACHE_TTL = 30 * 60       # metadata: 30 min
URL_TTL   = 15 * 60       # fallback si no podemos leer expire
SEARCH_TTL = 24 * 60 * 60 # cache 24h para búsquedas ATV por query
MAX_WORKERS = 6           # paralelismo I/O-bound razonable
_cache: dict[str, dict] = {}

# --- arriba del archivo, junto a imports/globales ---
# Creamos UNA SOLA vez el cookiefile para yt_dlp (evita I/O por request)
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

cookies_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cookies.txt"))
COOKIEFILE = "/root/musicappbackend/cookies.txt"

# Reusamos sesión HTTP para keep-alive real, con pool decente
_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "*/*",
    "Connection": "keep-alive",
})
_adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=1)
_SESSION.mount("https://", _adapter)
_SESSION.mount("http://", _adapter)

# Executor global para trabajos en segundo plano (prefetch)
_BACKGROUND_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_WORKERS)

def _ydl_for(client: str) -> yt_dlp.YoutubeDL:
    """
    Crea un YoutubeDL para el client indicado y usando el cookiefile inline.
    """
    effective_client = client  # <- usar el client que pasamos

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
        "extractor_args": {"youtube": {"player_client": [effective_client]}},
        "cachedir": os.path.join(tempfile.gettempdir(), "yt_dlp_cache"),
        "socket_timeout": 7,
        "retries": 0,
        "extractor_retries": 0,
        "sleep_requests": 0.0,
        "source_address": "0.0.0.0",
        "http_headers": {
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        },
        "cookiefile": COOKIEFILE,
    }
    return yt_dlp.YoutubeDL(opts)

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

def _extract_best_url(video_id: str):
    """
    Intenta varios clients y, si no hay info['url'], elige el mejor audio de formats[].
    """
    clients = ("web_music",)  # evitamos 'android' por PO token

    def pick_best_audio(info: dict) -> str | None:
        # 1) si yt_dlp ya resolvió un URL directo, usarlo
        direct = info.get("url")
        if direct and direct.startswith("http"):
            return direct

        # 2) elegir mejor audio-only desde formats
        fmts = info.get("formats") or []
        audios = [
            f for f in fmts
            if (f.get("vcodec") in (None, "none")) and (f.get("acodec") not in (None, "none")) and f.get("url")
        ]
        if not audios:
            return None

        # preferir m4a/aac > webm/opus; luego mayor bitrate (abr/tbr)
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
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}",
                download=False,
                process=False,  # <- evita "Requested format is not available"
            )
            url = pick_best_audio(info)
            if url:
                return info, url, c
        except Exception as e:
            last_err = e
            continue

    raise RuntimeError("no_audio_format" + (f": {last_err}" if last_err else ""))

def get_audio_info(video_id: str):
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
    # Fuerza Range en la primera request para evitar el "doble play"
    headers = {
        "Accept-Encoding": "identity",  # evita compresión que rompe rangos en algunos CDNs
        "Connection": "keep-alive",
    }
    if range_header:
        headers["Range"] = range_header
    else:
        headers["Range"] = "bytes=0-"   # <-- CLAVE

    r = _SESSION.get(url, headers=headers, stream=True, timeout=(5, 30), allow_redirects=True)

    resp_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-store",
        "Connection": "keep-alive",
    }

    ct = r.headers.get("Content-Type")
    media_type = ct if ct else "audio/webm"

    cl = r.headers.get("Content-Length")
    if cl:
        resp_headers["Content-Length"] = cl

    cr = r.headers.get("Content-Range")
    if cr:
        resp_headers["Content-Range"] = cr

    return StreamingResponse(
        r.iter_content(chunk_size=64 * 1024),  # 64KB mantiene el buffer activo rápido
        media_type=media_type,
        headers=resp_headers,
        status_code=r.status_code,
    )

# ---------- Helpers de performance (OMV→ATV + Prefetch + Warm head) ----------

_norm_re_strip = re.compile(r"(\(|\[).{0,80}?(\)|\])", re.IGNORECASE)
_norm_re_noise = re.compile(
    r"\b(official\s*video|video\s*oficial|video\s*clip|lyrics?|audio\s*only|HD|4K)\b",
    re.IGNORECASE
)

def _normalize_query(artist_names: str, title: str) -> str:
    base = f"{artist_names} {title}".strip() if artist_names else (title or "").strip()
    if not base:
        return ""
    base = _norm_re_strip.sub("", base)
    base = _norm_re_noise.sub("", base)
    base = re.sub(r"\s{2,}", " ", base).strip()
    return base

def _search_atv_first(q: str) -> str | None:
    if not q:
        return None
    ck = f"search_atv:{q.lower()}"
    cached = get_cached(ck)
    if cached is not None:
        return (cached or {}).get("videoId")
    yt_local = InnerTube("WEB_REMIX")
    sresp = yt_local.search(q)
    songs = parse_search_songs(sresp, strict_atv=True)
    vid = songs[0]["videoId"] if songs else None
    set_cached(ck, {"videoId": vid}, SEARCH_TTL)
    return vid

def _resolve_omv_to_atv_concurrent(tracks: list[dict]) -> None:
    jobs = []
    for idx, t in enumerate(tracks):
        if t.get("musicVideoType") == "MUSIC_VIDEO_TYPE_ATV":
            continue
        title = (t.get("title") or "").strip()
        artist_names = ", ".join([a.get("name", "").strip() for a in (t.get("artists") or []) if a.get("name")])
        q = _normalize_query(artist_names, title)
        if not q:
            continue
        jobs.append((idx, q))
    if not jobs:
        return
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(jobs))) as ex:
        futures = {ex.submit(_search_atv_first, q): (idx, q) for idx, q in jobs}
        for fut in as_completed(futures):
            idx, _ = futures[fut]
            try:
                vid = fut.result()
                if vid:
                    tracks[idx]["videoId"] = vid
                    tracks[idx]["musicVideoType"] = "MUSIC_VIDEO_TYPE_ATV"
            except Exception:
                continue

def _prefetch_audio_background(video_ids: list[str]) -> None:
    vids = [v for v in dict.fromkeys(video_ids) if v]
    if not vids:
        return
    def _task():
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(vids))) as ex:
            futs = [ex.submit(get_audio_info, v) for v in vids]
            for _ in as_completed(futs):
                pass
    _BACKGROUND_EXECUTOR.submit(_task)

def _warm_head_sync(video_id: str, timeout_s: float = 0.45) -> None:
    """
    Calienta SOLO el primer track: resuelve URL y toca 1 byte para dejar
    la conexión y TLS en caliente. Respeta un presupuesto de tiempo.
    """
    if not video_id:
        return
    def _do():
        data = get_audio_info(video_id)
        _probe_url(data["direct_url"])
    # usamos un executor efímero para respetar timeout sin bloquear el thread actual
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_do)
        try:
            fut.result(timeout=timeout_s)
        except Exception:
            pass

# --- AUDIO ENDPOINTS ---
@router.get("/play")
def play_song(
    request: Request,
    id: str = Query(..., description="YouTube video ID"),
    redir: int = Query(1, description="1=redirect (default), 0=JSON url, 2=proxy stream"),
):
    try:
        print(f"[play] ➤ solicitando ID: {id}")
        data = get_audio_info(id)
        audio_url = data["direct_url"]

        if redir == 2:
            # 🔁 Proxy streaming con soporte Range (evita 403 del CDN en el cliente)
            print(f"[play] 🛰️ PROXY stream → {audio_url[:80]}...")
            range_header = request.headers.get("range")
            return _stream_from_url(audio_url, range_header)

        if redir == 1:
            print(f"[play] 🔀 FORZANDO REDIRECT 307 → {audio_url[:80]}...")
            return RedirectResponse(url=audio_url, status_code=307)

        print(f"[play] 📦 devolviendo JSON url")
        return JSONResponse({"url": audio_url})

    except Exception as e:
        print(f"[ERROR /play] ❌ id={id} → {str(e)}")
        return JSONResponse(
            status_code=502,
            content={"error": "no_stream", "detail": str(e), "id": id},
        )

@router.post("/prefetch")
def prefetch_songs(payload: dict = Body(...)):
    raw_ids = payload.get("ids", [])
    ids = list(dict.fromkeys([str(i).strip() for i in raw_ids if i]))[:50]
    if not ids:
        return {"ok": True, "total": 0, "warmed_info": 0, "errors": 0}

    warmed_info = 0
    errors = 0
    def _one(vid: str):
        try:
            data = get_audio_info(vid)
            return 1 if data.get("direct_url") else 0
        except Exception:
            return -1

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(ids))) as ex:
        futs = [ex.submit(_one, vid) for vid in ids]
        for f in as_completed(futs):
            r = f.result()
            if r == 1:
                warmed_info += 1
            elif r == -1:
                errors += 1

    return {
        "ok": True,
        "total": len(ids),
        "warmed_info": warmed_info,
        "errors": errors,
    }

# --- SEARCH ---

@router.get("/search")
def search_music(q: str = Query(..., description="Texto a buscar")):
    cached = get_cached(f"search:{q}")
    if cached:
        return cached

    yt = InnerTube("WEB_REMIX")
    response = yt.search(q)

    artists = parse_search_artists(response)
    songs   = parse_search_songs(response, strict_atv=True)

    result = {"query": q, "artists": artists, "songs": songs}
    set_cached(f"search:{q}", result)
    return result

# --- ARTIST ---

def _artist_payload(artist_id: str):
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

    return {
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

@router.get("/artist")
def get_artist_q(id: str = Query(...)):
    return _artist_payload(id)

@router.get("/artist/{id}")
def get_artist_p(id: str = Path(...)):
    return _artist_payload(id)

# --- ALBUM ---

def _album_payload(album_id: str):
    yt = InnerTube("WEB_REMIX")
    response = yt.browse(album_id)

    tracks = parse_album_tracks(response)

    # OMV -> ATV en paralelo
    _resolve_omv_to_atv_concurrent(tracks)

    # Prefetch en background de TODO el álbum
    _prefetch_audio_background([t.get("videoId") for t in tracks])

    # Warm-up con presupuesto SOLO del primer tema (latencia del primer play)
    head_id = next((t.get("videoId") for t in tracks if t.get("videoId")), None)
    _warm_head_sync(head_id, timeout_s=0.45)

    payload = {
        "id": album_id,
        "info": parse_album_info(response),
        "tracks": tracks,
    }
    set_cached(f"album:{album_id}", payload, 30 * 60)
    return payload

@router.get("/album")
def get_album_q(id: str = Query(...)):
    cached = get_cached(f"album:{id}")
    if cached:
        return cached
    return _album_payload(id)

@router.get("/album/{id}")
def get_album_p(id: str = Path(...)):
    cached = get_cached(f"album:{id}")
    if cached:
        return cached
    return _album_payload(id)