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

from services.activity_service import try_log_activity_from_request
from services.supabase_service import db_as_user  # ← NUEVO

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
        direct = info.get("url")
        if direct and direct.startswith("http"):
            return direct
        fmts = info.get("formats") or []
        audios = [
            f for f in fmts
            if (f.get("vcodec") in (None, "none")) and (f.get("acodec") not in (None, "none")) and f.get("url")
        ]
        if not audios:
            return None
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
                process=False,
            )
            url = pick_best_audio(info)
            if url:
                return info, url, c
        except Exception as e:
            last_err = e
            continue

    raise RuntimeError("no_audio_format" + (f": {last_err}" if last_err else ""))

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

# --- OMV → ATV guard ---
def _force_atv_id(video_id: str) -> str:
    """
    Si el ID es de un OMV, lo mapea a la pista de audio (ATV) usando el buscador YTM.
    Si no encuentra, devuelve el original.
    """
    try:
        ydl = _ydl_for("web_music")
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}",
            download=False, process=False
        )
        title = (info.get("track") or info.get("title") or "").strip()
        artist = (info.get("artist") or info.get("uploader") or "").strip()

        if (not info.get("track")) and " - " in title and not artist:
            parts = title.split(" - ", 1)
            artist, title = parts[0].strip(), parts[1].strip()

        q = _normalize_query(artist, title)
        atv = _search_atv_first(q) if q else None
        return atv or video_id
    except Exception:
        return video_id

def get_audio_info(video_id: str):
    forced_id = _force_atv_id(video_id)
    if forced_id != video_id:
        video_id = forced_id

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
    headers = {
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
    }
    if range_header:
        headers["Range"] = range_header
    else:
        headers["Range"] = "bytes=0-"

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
        r.iter_content(chunk_size=64 * 1024),
        media_type=media_type,
        headers=resp_headers,
        status_code=r.status_code,
    )

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
    if not video_id:
        return
    def _do():
        data = get_audio_info(video_id)
        _probe_url(data["direct_url"])
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
        id = _force_atv_id(id)
        print(f"[play] ➤ solicitando ID: {id}")
        data = get_audio_info(id)
        audio_url = data["direct_url"]

        if redir == 2:
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
    ids = list(
        dict.fromkeys([_force_atv_id(str(i).strip()) for i in raw_ids if i])
    )[:50]
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
def search_music(request: Request, q: str = Query(..., description="Texto a buscar")):
    auth_hdr = request.headers.get("Authorization", "")
    print(f"[search] Authorization len={len(auth_hdr)} sample={auth_hdr[:20]}...")
    mw_user = getattr(request.state, "user", None)
    print(f"[search] middleware.user => {mw_user}")

    cached = get_cached(f"search:{q}")
    if cached:
        try_log_activity_from_request(
            request,
            event_type="search",
            entity_type="query",
            metadata={"query": q},
        )
        return cached

    yt = InnerTube("WEB_REMIX")
    response = yt.search(q)

    artists = parse_search_artists(response)
    songs   = parse_search_songs(response, strict_atv=True)

    result = {"query": q, "artists": artists, "songs": songs}
    set_cached(f"search:{q}", result)

    try_log_activity_from_request(
        request,
        event_type="search",
        entity_type="query",
        metadata={"query": q},
    )
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

    _resolve_omv_to_atv_concurrent(tracks)
    _prefetch_audio_background([t.get("videoId") for t in tracks])
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

# --- NUEVOS: endpoints livianos para registrar 'play' de álbum/artista ---

@router.post("/plays/albums/{album_id}")
def log_play_album(request: Request, album_id: str = Path(...), body: dict | None = Body(None)):
    b = body or {}
    source = b.get("source")
    meta = {}
    if source: meta["source"] = source
    # 👇 NUEVO: nombre + thumbnail del álbum (opcionales)
    dn = b.get("display_name") or b.get("name") or b.get("title")
    th = b.get("thumbnail_url") or b.get("thumbnail")
    if dn: meta["display_name"] = dn
    if th: meta["thumbnail_url"] = th

    try_log_activity_from_request(
        request,
        event_type="play",
        entity_type="album",
        entity_id=album_id,
        context_type="album",
        context_id=album_id,
        metadata=meta or None,
    )
    return {"ok": True}

@router.post("/plays/artists/{artist_id}")
def log_play_artist(request: Request, artist_id: str = Path(...), body: dict | None = Body(None)):
    b = body or {}
    source = b.get("source")
    meta = {}
    if source: meta["source"] = source
    # 👇 NUEVO: nombre + thumbnail del artista (opcionales)
    dn = b.get("display_name") or b.get("name") or b.get("title")
    th = b.get("thumbnail_url") or b.get("thumbnail")
    if dn: meta["display_name"] = dn
    if th: meta["thumbnail_url"] = th

    try_log_activity_from_request(
        request,
        event_type="play",
        entity_type="artist",
        entity_id=artist_id,
        context_type="artist",
        context_id=artist_id,
        metadata=meta or None,
    )
    return {"ok": True}

# --- LIKE / UNLIKE (no duplica: usa upsert del activity_service) ---

@router.post("/likes/tracks/{track_id}")
def like_track(request: Request, track_id: str = Path(...), body: dict | None = Body(None)):
    source = (body or {}).get("source")
    try_log_activity_from_request(
        request,
        event_type="like",
        entity_type="track",
        entity_id=track_id,
        context_type="track",
        context_id=track_id,
        metadata={"source": source} if source else None,
    )
    return {"ok": True}

@router.post("/unlikes/tracks/{track_id}")
def unlike_track(request: Request, track_id: str = Path(...), body: dict | None = Body(None)):
    source = (body or {}).get("source")
    try_log_activity_from_request(
        request,
        event_type="unlike",
        entity_type="track",
        entity_id=track_id,
        context_type="track",
        context_id=track_id,
        metadata={"source": source} if source else None,
    )
    return {"ok": True}

@router.post("/likes/albums/{album_id}")
def like_album(request: Request, album_id: str = Path(...), body: dict | None = Body(None)):
    source = (body or {}).get("source")
    try_log_activity_from_request(
        request,
        event_type="like",
        entity_type="album",
        entity_id=album_id,
        context_type="album",
        context_id=album_id,
        metadata={"source": source} if source else None,
    )
    return {"ok": True}

@router.post("/unlikes/albums/{album_id}")
def unlike_album(request: Request, album_id: str = Path(...), body: dict | None = Body(None)):
    source = (body or {}).get("source")
    try_log_activity_from_request(
        request,
        event_type="unlike",
        entity_type="album",
        entity_id=album_id,
        context_type="album",
        context_id=album_id,
        metadata={"source": source} if source else None,
    )
    return {"ok": True}

@router.post("/likes/artists/{artist_id}")
def like_artist(request: Request, artist_id: str = Path(...), body: dict | None = Body(None)):
    source = (body or {}).get("source")
    try_log_activity_from_request(
        request,
        event_type="like",
        entity_type="artist",
        entity_id=artist_id,
        context_type="artist",
        context_id=artist_id,
        metadata={"source": source} if source else None,
    )
    return {"ok": True}

@router.post("/unlikes/artists/{artist_id}")
def unlike_artist(request: Request, artist_id: str = Path(...), body: dict | None = Body(None)):
    source = (body or {}).get("source")
    try_log_activity_from_request(
        request,
        event_type="unlike",
        entity_type="artist",
        entity_id=artist_id,
        context_type="artist",
        context_id=artist_id,
        metadata={"source": source} if source else None,
    )
    return {"ok": True}

@router.post("/likes/playlists/{playlist_id}")
def like_playlist(request: Request, playlist_id: str = Path(...), body: dict | None = Body(None)):
    source = (body or {}).get("source")
    try_log_activity_from_request(
        request,
        event_type="like",
        entity_type="playlist",
        entity_id=playlist_id,
        context_type="playlist",
        context_id=playlist_id,
        metadata={"source": source} if source else None,
    )
    return {"ok": True}

@router.post("/unlikes/playlists/{playlist_id}")
def unlike_playlist(request: Request, playlist_id: str = Path(...), body: dict | None = Body(None)):
    source = (body or {}).get("source")
    try_log_activity_from_request(
        request,
        event_type="unlike",
        entity_type="playlist",
        entity_id=playlist_id,
        context_type="playlist",
        context_id=playlist_id,
        metadata={"source": source} if source else None,
    )
    return {"ok": True}

# --- LIKES: consulta de estado (NO duplica, solo lectura) ---  ← NUEVO

def _db_for_request_simple(request: Request):
    jwt = (request.headers.get("Authorization") or "").replace("Bearer ", "")
    return db_as_user(jwt)

def _last_event_for_track(db, track_id: str):
    r = (
        db.table("user_activity")
        .select("event_type,occurred_at")
        .eq("entity_type", "track")
        .eq("entity_id", track_id)
        .in_("event_type", ["like", "unlike"])
        .order("occurred_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = r.data or []
    return rows[0]["event_type"] if rows else None

@router.get("/likes/tracks/{track_id}")
def is_track_liked(request: Request, track_id: str = Path(...)):
    """
    Devuelve si el track está actualmente en 'me gusta' para el usuario.
    Regla: último evento ('like' vs 'unlike') gana.
    """
    try:
        db = _db_for_request_simple(request)
        last = _last_event_for_track(db, track_id)
        return {"track_id": track_id, "liked": (last == "like")}
    except Exception as e:
        print(f"[likes][single][ERROR] {e}")
        return JSONResponse(status_code=500, content={"ok": False, "error": "likes_check_failed"})

@router.post("/likes/tracks/check")
def are_tracks_liked(request: Request, payload: dict = Body(...)):
    """
    Body: { ids: string[] }  ->  { liked: string[] }
    Responde sólo los ids que están liked (último evento = 'like').
    """
    raw_ids = payload.get("ids", [])
    ids = [str(i) for i in raw_ids if i][:200]
    if not ids:
        return {"liked": []}
    try:
        db = _db_for_request_simple(request)
        r = (
            db.table("user_activity")
            .select("entity_id, event_type, occurred_at")
            .eq("entity_type", "track")
            .in_("entity_id", ids)
            .in_("event_type", ["like", "unlike"])
            .order("entity_id", desc=False)
            .order("occurred_at", desc=True)
            .execute()
        )
        rows = r.data or []
        last_by_id = {}
        for row in rows:
            tid = row["entity_id"]
            if tid in last_by_id:
                continue
            last_by_id[tid] = row["event_type"]
        liked = [tid for tid, ev in last_by_id.items() if ev == "like"]
        return {"liked": liked}
    except Exception as e:
        print(f"[likes][bulk][ERROR] {e}")
        return JSONResponse(status_code=500, content={"ok": False, "error": "likes_check_failed"})

# --- helper arriba del endpoint ---
def _first(*vals):
    for v in vals:
        if v not in (None, "", [], {}):
            return v
    return None

# --- ME / RECENT (álbumes y artistas reproducidos recientemente) ---
@router.get("/me/recent")
def get_recent_plays(request: Request, limit: int = 20):
    """
    Últimos álbumes/artistas reproducidos por el usuario actual.
    - Devuelve SOLO: type, id, occurred_at, name (opcional), thumbnail_url (opcional)
    - Ordenado por occurred_at DESC
    - Dedup por (type, id): se queda con el MÁS RECIENTE
    - Aplica 'limit' después de deduplicar
    """
    try:
        # auth básico
        jwt = (request.headers.get("Authorization") or "").replace("Bearer ", "").strip()
        if not jwt:
            return JSONResponse(status_code=401, content={"ok": False, "error": "unauthorized"})

        db = db_as_user(jwt)

        # Pedimos más filas que el límite para poder deduplicar sin quedarnos cortos
        hard_limit  = max(1, min(100, int(limit)))   # seguridad
        fetch_limit = min(3 * hard_limit, 150)       # hasta 3x para margen
        resp = (
            db.table("user_activity")
            .select("entity_type, entity_id, occurred_at, metadata")
            .eq("event_type", "play")
            .in_("entity_type", ["album", "artist"])
            .order("occurred_at", desc=True)
            .limit(fetch_limit)
            .execute()
        )
        rows = resp.data or []

        seen = set()   # (type, id)
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

            md  = row.get("metadata") or {}
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
                "type": t,                   # "album" | "artist"
                "id": i,
                "occurred_at": row.get("occurred_at"),
                "name": name,
                "thumbnail_url": thumb,
            })

            if len(items) >= hard_limit:
                break

        return {"items": items}

    except Exception as e:
        print(f"[recent][ERROR] {e}")
        return JSONResponse(status_code=500, content={"ok": False, "error": "recent_failed"})