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

cookies_path = os.path.join(os.path.dirname(__file__), "..", "cookies.txt")

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
    mobile_client = client.lower() in ("android", "ios")
    opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "extractor_args": {
            "youtube": {
                "player_client": [client],
            },
            "youtubepot-bgutilhttp": {
                "base_url": ["https://bgutil-ytdlp-pot-provider-latest.onrender.com"],
            },
        },
        "cachedir": os.path.join(tempfile.gettempdir(), "yt_dlp_cache"),
        "retries": 1,
        "extractor_retries": 1,
    }
    if not mobile_client and os.path.exists(cookies_path):
        opts["cookiefile"] = cookies_path
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
    Intentamos primero clientes móviles (rápidos para m4a/140),
    luego variantes web como fallback.
    """
    for client in ("android", "ios", "web_music", "mweb", "web"):
        try:
            ydl = _ydl_for(client)
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            direct_url = info.get("url")
            if direct_url and direct_url.startswith("http"):
                return info, direct_url, client
        except Exception:
            continue
    raise RuntimeError("no_audio_format")

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
    headers = {}
    if range_header:
        headers["Range"] = range_header

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

    # ↓ Chunk más chico para que el navegador tenga audio listo antes
    return StreamingResponse(
        r.iter_content(chunk_size=64 * 1024),
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
    redir: int = Query(0, description="Si 1, redirige al CDN en vez de proxyear")
):
    """
    Devuelve stream de audio con soporte Range y refresh de URL si expiró.
    Política de latencia:
      - Primera vez que se reproduce un ID → proxy streaming para evitar DNS/TLS frío del cliente.
      - Veces siguientes → 307 Redirect al CDN (menos carga).
    """
    try:
        data = get_audio_info(id)
        audio_url = data["direct_url"]
        approx_ttl = data.get("ttl", URL_TTL)

        served = int(data.get("served", 0))
        _cache[id]["served"] = served + 1

        if approx_ttl <= 10:
            if not _probe_url(audio_url):
                data = get_audio_info(id)
                audio_url = data["direct_url"]
                approx_ttl = data.get("ttl", URL_TTL)

        print(f"[play] id={id} via client={data.get('client')} ttl≈{approx_ttl}s served={served}")

        if served == 0:
            range_hdr = request.headers.get("Range")
            return _stream_from_url(audio_url, range_hdr)

        return RedirectResponse(url=audio_url, status_code=307)

    except Exception as e:
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