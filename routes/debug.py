# routes/debug.py
from fastapi import APIRouter, Query
from innertube import InnerTube
from services.cache_service import get_cached, set_cached
from concurrent.futures import ThreadPoolExecutor, as_completed
import re

router = APIRouter()

# -------------------
# InnerTube singleton (mejor latencia por keep-alive)
# -------------------
_YT = None
def _get_yt():
    global _YT
    if _YT is None:
        _YT = InnerTube("WEB_REMIX")
    return _YT

# -------------------
# Regex precompilado (micro-optimización)
# -------------------
_DURATION_RE = re.compile(
    r"(?:(\d+)\s+hours?,\s*)?(?:(\d+)\s+minutes?,\s*)?(\d+)\s+seconds?",
    re.IGNORECASE,
)

@router.get("/")
def playlists_root():
    return {"message": "DEBUG route OK"}

@router.get("/search_debug")
def search_debug(q: str = Query(..., description="Texto a buscar")):
    """
    Devuelve la respuesta CRUDA de YouTube Music (WEB_REMIX).
    Sirve para debug y ver toda la estructura.
    """
    try:
        yt = _get_yt()
        response = yt.search(q)
        return response   # 🔴 devolvemos TODO, sin filtrar
    except Exception as e:
        return {"error": "search_error", "detail": str(e)}

@router.get("/artist_debug")
def artist_debug(id: str = Query(..., description="Artist browseId")):
    try:
        yt = _get_yt()
        response = yt.browse(id)   # 👈 browse con el browseId del artista
        return response
    except Exception as e:
        return {"error": "artist_debug_error", "detail": str(e), "id": id}

@router.get("/artist_debug_contents")
def artist_debug_contents(id: str = Query(..., description="Artist browseId")):
    try:
        yt = _get_yt()
        response = yt.browse(id)

        # navegar directo a contents
        contents = (
            response.get("contents", {})
            .get("singleColumnBrowseResultsRenderer", {})
            .get("tabs", [])[0]
            .get("tabRenderer", {})
            .get("content", {})
            .get("sectionListRenderer", {})
            .get("contents", [])
        )

        return {"artistId": id, "contents": contents}

    except Exception as e:
        return {"error": "artist_debug_contents_error", "detail": str(e), "id": id}

@router.get("/album_debug")
def album_debug(id: str = Query(..., description="Album browseId")):
    """
    Devuelve la respuesta completa de un álbum desde YouTube Music.
    """
    yt = _get_yt()
    response = yt.browse(id)
    return response

# -------------------
# helpers genéricos
# -------------------
def _dig(cur, path, default=None):
    """Soporta dicts y listas en un path tipo ['a',0,'b']"""
    for k in path:
        if isinstance(k, int):
            if isinstance(cur, (list, tuple)) and 0 <= k < len(cur):
                cur = cur[k]
            else:
                return default
        else:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                return default
    return cur

def _runs(mrlir, col_idx):
    return _dig(mrlir, ["flexColumns", col_idx, "musicResponsiveListItemFlexColumnRenderer", "text", "runs"], []) or []

# ---------- THUMBNAILS (SIEMPRE) ----------
def _mk_std_thumbs_from_video(video_id: str | None):
    """Fallback rápido: genera thumbnails estándar de YouTube por videoId."""
    if not video_id:
        return []
    base = f"https://i.ytimg.com/vi/{video_id}"
    # Ordenado de menor a mayor (aprox)
    return [
        {"url": f"{base}/default.jpg"},
        {"url": f"{base}/mqdefault.jpg"},
        {"url": f"{base}/hqdefault.jpg"},
        {"url": f"{base}/sddefault.jpg"},
        {"url": f"{base}/maxresdefault.jpg"},
    ]

def _thumbs_from_mrlir(mrlir, video_id=None):
    """
    Intenta múltiples rutas conocidas en MRLIR.
    Si no hay ninguna, genera por videoId.
    """
    cand_paths = [
        ["thumbnail", "musicThumbnailRenderer", "thumbnail", "thumbnails"],
        ["thumbnail", "thumbnails"],
        ["overlay", "musicItemThumbnailOverlayRenderer", "thumbnail", "thumbnails"],
        ["flexColumns", 0, "musicResponsiveListItemFlexColumnRenderer", "text", "runs", 0,
         "navigationEndpoint", "watchEndpoint", "thumbnail", "thumbnails"],
    ]
    for p in cand_paths:
        thumbs = _dig(mrlir, p, [])
        if thumbs:
            return thumbs
    return _mk_std_thumbs_from_video(video_id)

def _thumbs_from_queue_item(it, video_id=None):
    """
    PlayQueue item → intenta rutas típicas, si no, genera por videoId.
    """
    thumbs = _dig(it, ["thumbnail", "thumbnails"], []) or _dig(it, ["thumbnailRenderer", "thumbnail", "thumbnails"], [])
    if thumbs:
        return thumbs
    return _mk_std_thumbs_from_video(video_id)

# ---------- DURACIÓN ----------
def _parse_duration(info_runs, accessibility_label):
    # buscar "mm:ss" o "h:mm:ss" en los runs
    for r in reversed(info_runs):
        txt = (r or {}).get("text", "")
        parts = txt.split(":")
        if len(parts) in (2, 3) and all(p.isdigit() for p in parts):
            return txt
    # fallback desde accessibility
    if accessibility_label:
        m = _DURATION_RE.search(accessibility_label)
        if m:
            h = int(m.group(1) or 0)
            mnt = int(m.group(2) or 0)
            sec = int(m.group(3) or 0)
            total_sec = h*3600 + mnt*60 + sec
            if total_sec >= 3600:
                hh = total_sec // 3600
                mm = (total_sec % 3600) // 60
                ss = total_sec % 60
                return f"{hh}:{mm:02d}:{ss:02d}"
            else:
                mm = total_sec // 60
                ss = total_sec % 60
                return f"{mm}:{ss:02d}"
    return None

def extract_song_item(mrlir):
    title_runs = _runs(mrlir, 0)
    info_runs  = _runs(mrlir, 1)

    # título
    title = _dig(title_runs, [0, "text"]) or "".join((r or {}).get("text", "") for r in title_runs) or None

    # artistas
    artists = []
    for r in info_runs:
        be = _dig(r, ["navigationEndpoint", "browseEndpoint"]) or {}
        page_type = _dig(r, ["navigationEndpoint","browseEndpoint","browseEndpointContextSupportedConfigs",
                             "browseEndpointContextMusicConfig","pageType"])
        if page_type == "MUSIC_PAGE_TYPE_ARTIST":
            artists.append({
                "name": r.get("text", ""),
                "browseId": be.get("browseId")
            })

    # álbum
    album = None
    for r in info_runs:
        be = _dig(r, ["navigationEndpoint", "browseEndpoint"]) or {}
        page_type = _dig(r, ["navigationEndpoint","browseEndpoint","browseEndpointContextSupportedConfigs",
                             "browseEndpointContextMusicConfig","pageType"])
        if page_type == "MUSIC_PAGE_TYPE_ALBUM":
            album = {
                "name": r.get("text", ""),
                "browseId": be.get("browseId")
            }
            break

    accessibility_label = _dig(mrlir, ["accessibility","accessibilityData","label"])
    duration = _parse_duration(info_runs, accessibility_label)

    # videoId y tipo (ATV)
    video_id = (
        _dig(mrlir, ["playlistItemData", "videoId"])
        or _dig(title_runs, [0, "navigationEndpoint", "watchEndpoint", "videoId"])
        or _dig(mrlir, ["overlay","musicItemThumbnailOverlayRenderer","content","musicPlayButtonRenderer",
                        "playNavigationEndpoint","watchEndpoint","videoId"])
    )
    music_video_type = (
        _dig(title_runs, [0,"navigationEndpoint","watchEndpoint","watchEndpointMusicSupportedConfigs",
                          "watchEndpointMusicConfig","musicVideoType"])
        or _dig(mrlir, ["overlay","musicItemThumbnailOverlayRenderer","content","musicPlayButtonRenderer",
                        "playNavigationEndpoint","watchEndpoint","watchEndpointMusicSupportedConfigs",
                        "watchEndpointMusicConfig","musicVideoType"])
    )

    # ✔ thumbnails robusto
    thumbs = _thumbs_from_mrlir(mrlir, video_id)

    return {
        "title": title,
        "artists": artists,
        "album": album,
        "duration": duration,
        "videoId": video_id,
        "musicVideoType": music_video_type,
        "thumbnails": thumbs,
        # runs crudos por si necesitás debug
        "title_runs": title_runs,
        "info_runs": info_runs,
    }

def extract_songs_from_resp(resp: dict):
    # encontrar el tab seleccionado
    tabs = _dig(resp, ["contents","tabbedSearchResultsRenderer","tabs"], [])
    selected_tab = None
    for t in tabs:
        tr = t.get("tabRenderer") or t.get("expandableTabRenderer")
        if tr and tr.get("selected"):
            selected_tab = tr
            break
    if not selected_tab:
        return []

    # secciones → shelf "Songs"/"Canciones"
    sections = _dig(selected_tab, ["content","sectionListRenderer","contents"], [])
    for sec in sections:
        shelf = sec.get("musicShelfRenderer")
        if not shelf:
            continue
        shelf_title = "".join((r or {}).get("text","") for r in _dig(shelf, ["title","runs"], [])).strip().lower()
        if shelf_title not in ("songs", "canciones"):
            continue

        out = []
        for it in shelf.get("contents", []):
            mrlir = it.get("musicResponsiveListItemRenderer")
            if mrlir:
                out.append(extract_song_item(mrlir))
        return out
    return []

# -------------------
# endpoint
# -------------------
@router.get("/search_songs_full")
def search_songs_full(q: str = Query(..., description="Texto a buscar")):
    """
    Busca SOLO canciones (shelf 'Songs/Canciones') y devuelve título, artistas, album, duración,
    videoId (ATV), thumbnails, y runs crudos.
    """
    try:
        yt = _get_yt()
        resp = yt.search(q)
        songs = extract_songs_from_resp(resp)
        return {"q": q, "count": len(songs), "songs": songs}
    except Exception as e:
        return {"error": "search_songs_full_error", "detail": str(e)}

# -------------------
# ALBUM → SOLO AUDIOS (ATV) + RESOLVER OMV→ATV POR BÚSQUEDA
# -------------------

def _duration_to_seconds(s: str | None) -> int | None:
    if not s: return None
    parts = s.split(":")
    if not all(p.isdigit() for p in parts): return None
    if len(parts) == 2:      # mm:ss
        m, ss = int(parts[0]), int(parts[1])
        return m*60 + ss
    if len(parts) == 3:      # h:mm:ss
        h, m, ss = int(parts[0]), int(parts[1]), int(parts[2])
        return h*3600 + m*60 + ss
    return None

def _album_artists(resp):
    runs = _dig(resp, ["header","musicDetailHeaderRenderer","subtitle","runs"], []) or []
    out = []
    for r in runs:
        page_type = _dig(r, ["navigationEndpoint","browseEndpoint",
                             "browseEndpointContextSupportedConfigs","browseEndpointContextMusicConfig","pageType"])
        if page_type == "MUSIC_PAGE_TYPE_ARTIST":
            out.append({
                "name": r.get("text",""),
                "browseId": _dig(r, ["navigationEndpoint","browseEndpoint","browseId"])
            })
    return out

def _album_title(resp):
    return _dig(resp, ["header","musicDetailHeaderRenderer","title","runs",0,"text"])

def _levenshtein_like(a: str, b: str) -> float:
    # baratito: normaliza y compara por contención; 1.0 exacto, 0.8 si parcial, 0 si nada
    if not a or not b: return 0.0
    ax, bx = a.strip().lower(), b.strip().lower()
    if ax == bx: return 1.0
    if ax in bx or bx in ax: return 0.8
    return 0.0

def _best_atv_from_search(yt, title, artist_names, target_album, target_dur_s, cache_ttl=900):
    """
    Busca un ATV para (title, artist) en el shelf 'Songs'.
    Scoring:
      +1.0 si título exacto (o 0.8 si parcial)
      +0.5 si artista coincide (alguno)
      +0.5 si álbum coincide (parcial)
      -|Δdur|/60 como penalización suave (hasta -1 aprox si 60s desvío)
    """
    # cache por título+artista
    key = f"resolve_atv:{title}:{','.join(artist_names or [''])}"
    cached = get_cached(key)
    if cached is not None:
        return cached

    queries = []
    if artist_names:
        queries.append(f"{title} {artist_names[0]}")
    queries.append(title)  # fallback sin artista
    if artist_names:
        queries.append(f"{title} {artist_names[0]} topic")  # a veces “Topic” trae el audio

    best, best_score = None, -999.0

    for q in queries:
        try:
            resp = yt.search(q)
        except Exception:
            continue
        songs = extract_songs_from_resp(resp)  # tu helper que devuelve solo el shelf Songs
        for s in songs:
            if (s.get("musicVideoType") != "MUSIC_VIDEO_TYPE_ATV") or not s.get("videoId"):
                continue
            cand_title = s.get("title") or ""
            cand_album = (s.get("album") or {}).get("name","")
            cand_artists = [a.get("name","") for a in (s.get("artists") or [])]
            cand_dur_s = _duration_to_seconds(s.get("duration"))

            score = 0.0
            score += _levenshtein_like(cand_title, title) * 1.0
            if artist_names and cand_artists:
                if any(_levenshtein_like(x, y) >= 0.8 for x in cand_artists for y in artist_names):
                    score += 0.5
            if target_album and cand_album:
                if _levenshtein_like(cand_album, target_album) >= 0.8:
                    score += 0.5
            if target_dur_s and cand_dur_s:
                diff = abs(cand_dur_s - target_dur_s)
                score -= min(diff/60.0, 1.0)  # penaliza si se aleja >60s

            if score > best_score:
                best, best_score = s, score

        # si ya encontramos un match muy bueno, cortamos
        if best and best_score >= 1.5:
            break

    set_cached(key, best, ttl=cache_ttl)
    return best

def _get_watch(mrlir):
    return _dig(mrlir, [
        "overlay","musicItemThumbnailOverlayRenderer","content","musicPlayButtonRenderer",
        "playNavigationEndpoint","watchEndpoint"
    ], {}) or _dig(mrlir, [
        "flexColumns",0,"musicResponsiveListItemFlexColumnRenderer","text","runs",0,
        "navigationEndpoint","watchEndpoint"
    ], {}) or {}

def _get_mvtype(mrlir):
    return (
        _dig(mrlir, [
            "overlay","musicItemThumbnailOverlayRenderer","content","musicPlayButtonRenderer",
            "playNavigationEndpoint","watchEndpoint","watchEndpointMusicSupportedConfigs",
            "watchEndpointMusicConfig","musicVideoType"
        ])
        or _dig(mrlir, [
            "flexColumns",0,"musicResponsiveListItemFlexColumnRenderer","text","runs",0,
            "navigationEndpoint","watchEndpoint","watchEndpointMusicSupportedConfigs",
            "watchEndpointMusicConfig","musicVideoType"
        ])
    )

def _is_audio_track(mrlir):
    mvtype = _get_mvtype(mrlir)
    if mvtype == "MUSIC_VIDEO_TYPE_ATV":
        return True
    if mvtype in ("MUSIC_VIDEO_TYPE_OMV", "MUSIC_VIDEO_TYPE_UGC"):
        return False
    watch = _get_watch(mrlir)
    playlist_id = (watch.get("playlistId") or "")
    has_idx = ("index" in watch) or ("playlistSetVideoId" in watch)
    return playlist_id.startswith("OLAK5") and has_idx

def _iter_album_track_mrlir(resp):
    sections = _dig(resp, [
        "contents","twoColumnBrowseResultsRenderer","secondaryContents",
        "sectionListRenderer","contents"
    ], []) or []
    # fallback por si cambia layout
    tabs = _dig(resp, ["contents","singleColumnBrowseResultsRenderer","tabs"], []) or []
    for t in tabs:
        tr = t.get("tabRenderer") or t.get("expandableTabRenderer") or {}
        sections += _dig(tr, ["content","sectionListRenderer","contents"], []) or []

    for sec in sections:
        shelf = sec.get("musicShelfRenderer")
        if not shelf: continue
        for it in shelf.get("contents", []):
            mrlir = it.get("musicResponsiveListItemRenderer")
            if mrlir:
                yield mrlir

def _map_album_track(mrlir):
    data = extract_song_item(mrlir)
    watch = _get_watch(mrlir)
    data.update({
        "playlistId": watch.get("playlistId"),
        "index": watch.get("index"),
        "playlistSetVideoId": watch.get("playlistSetVideoId"),
    })
    return data

# -------------------
# AUDIO queue helpers (más rápido)
# -------------------

def _album_audio_playlist_id(resp):
    # 1) botón "Play" del header
    pid = _dig(resp, ["header","musicDetailHeaderRenderer","buttons",0,"buttonRenderer",
                      "navigationEndpoint","watchEndpoint","playlistId"])
    if pid and pid.startswith("OLAK5"): return pid

    # 2) items del menú del header (por si cambia el layout)
    items = _dig(resp, ["header","musicDetailHeaderRenderer","menu","menuRenderer","items"], []) or []
    for it in items:
        pid = _dig(it, ["menuNavigationItemRenderer","navigationEndpoint","watchEndpoint","playlistId"])
        if pid and pid.startswith("OLAK5"): return pid

    # 3) fallback: tomar el playlistId del primer track listado en el álbum
    for mrlir in _iter_album_track_mrlir(resp):
        pid = _get_watch(mrlir).get("playlistId")
        if pid and pid.startswith("OLAK5"): return pid
    return None

def _first_track_seed(resp):
    """Saca el primer videoId/index del listado del álbum para 'sembrar' la queue (acelera y evita truncados)."""
    for mrlir in _iter_album_track_mrlir(resp):
        watch = _get_watch(mrlir)
        vid = watch.get("videoId")
        idx = watch.get("index")
        if vid:
            try:
                idx_int = int(idx) if idx is not None else 0
            except Exception:
                idx_int = 0
            return vid, idx_int
    return None, None

def _collect_playlist_panel_items(node, out):
    # Busca recursivamente renderers de la queue
    if isinstance(node, dict):
        if "playlistPanelVideoRenderer" in node:
            out.append(node["playlistPanelVideoRenderer"])
        for v in node.values():
            _collect_playlist_panel_items(v, out)
    elif isinstance(node, list):
        for v in node:
            _collect_playlist_panel_items(v, out)
    return out

def _extract_queue_audio_tracks(queue_resp):
    items = _collect_playlist_panel_items(queue_resp, [])
    tracks = []
    for it in items:
        mvtype = _dig(it, ["navigationEndpoint","watchEndpoint",
                           "watchEndpointMusicSupportedConfigs","watchEndpointMusicConfig","musicVideoType"])
        # En la watch-playlist de AUDIO, a veces no viene mvtype. Excluimos sólo si dice OMV/UGC explícito.
        if mvtype in ("MUSIC_VIDEO_TYPE_OMV", "MUSIC_VIDEO_TYPE_UGC"):
            continue  # solo audio

        title = _dig(it, ["title","runs",0,"text"]) or _dig(it, ["title","simpleText"])
        video_id = _dig(it, ["videoId"]) or _dig(it, ["navigationEndpoint","watchEndpoint","videoId"])
        if not (video_id and title):
            continue

        # artistas
        artists = []
        for r in _dig(it, ["shortBylineText","runs"], []) or []:
            page_type = _dig(r, ["navigationEndpoint","browseEndpoint",
                                 "browseEndpointContextSupportedConfigs","browseEndpointContextMusicConfig","pageType"])
            if page_type == "MUSIC_PAGE_TYPE_ARTIST":
                artists.append({
                    "name": r.get("text",""),
                    "browseId": _dig(r, ["navigationEndpoint","browseEndpoint","browseId"])
                })

        tracks.append({
            "title": title,
            "artists": artists,
            "album": None,
            "duration": _dig(it, ["lengthText","runs",0,"text"]) or _dig(it, ["lengthText","simpleText"]),
            "videoId": video_id,
            "musicVideoType": "MUSIC_VIDEO_TYPE_ATV",  # la cola es de AUDIO
            "thumbnails": _thumbs_from_queue_item(it, video_id),
            "playlistId": _dig(it, ["navigationEndpoint","watchEndpoint","playlistId"]),
            "index": _dig(it, ["navigationEndpoint","watchEndpoint","index"]),
            "playlistSetVideoId": _dig(it, ["navigationEndpoint","watchEndpoint","playlistSetVideoId"]),
            "type": "audio"
        })
    # ordenar por índice si existe
    def _idx(t):
        try: return int(t.get("index"))
        except: return 1_000_000
    tracks.sort(key=_idx)
    return tracks

def _fetch_full_audio_queue(yt, apl_id, seed_vid=None, seed_idx=0):
    """
    Trae TODA la watch-playlist de audio.
    Sembramos con (videoId, index) del primer track para evitar colas cortadas.
    """
    body = {"playlistId": apl_id, "params": "wAEB"}
    if seed_vid is not None:
        body["videoId"] = seed_vid
        body["index"] = seed_idx

    data = yt.next(body)
    out = _extract_queue_audio_tracks(data)

    # continuations
    def _get_cont_token(d):
        return (
            _dig(d, ["continuationContents","playlistPanelContinuation","continuations",0,"nextContinuationData","continuation"])
            or _dig(d, ["contents","singleColumnMusicWatchNextResultsRenderer","tabbedRenderer",
                        "watchNextTabbedResultsRenderer","tabs",0,"tabRenderer","content",
                        "musicQueueRenderer","content","playlistPanelRenderer","continuations",0,
                        "nextContinuationData","continuation"])
        )
    cont = _get_cont_token(data)
    while cont:
        more = yt.next({"continuation": cont})
        out += _extract_queue_audio_tracks(more)
        cont = _get_cont_token(more)

    return out

# -------------------
# RESOLUCIÓN EN PARALELO (fallback OMV→ATV)
# -------------------

def _resolve_omv_batch(omv_list, album_artists, album_name, max_workers=6):
    """Resuelve OMV→ATV en paralelo para acelerar."""
    def job(omv):
        yt_local = InnerTube("WEB_REMIX")  # sesión por thread
        title = omv.get("title") or ""
        arts = [a.get("name","") for a in (omv.get("artists") or [])] or album_artists
        dur_s = _duration_to_seconds(omv.get("duration"))
        cand = _best_atv_from_search(yt_local, title, arts, album_name, dur_s)
        return (omv, cand)

    resolved = 0
    if not omv_list:
        return resolved

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(job, omv) for omv in omv_list]
        for f in as_completed(futures):
            omv, cand = f.result()
            if cand:
                omv.update({
                    "videoId": cand.get("videoId"),
                    "musicVideoType": "MUSIC_VIDEO_TYPE_ATV",
                    "duration": cand.get("duration") or omv.get("duration"),
                    "artists": cand.get("artists") or omv.get("artists") or [],
                    "album": cand.get("album") or omv.get("album"),
                    "type": "audio",
                    "resolvedFrom": "omv_search_fallback",
                })
                resolved += 1
    return resolved

# -------------------
# ENDPOINT
# -------------------

@router.get("/album_tracks_audio_resolved")
def album_tracks_audio_resolved(
    id: str = Query(..., description="Album browseId"),
    try_resolve: bool = True,
    max_resolve: int = 50,
    use_cache: bool = True
):
    """
    Devuelve pistas de audio (ATV) del álbum. Primero usa la watch-playlist de AUDIO
    (rápida). Sólo si eso falla (0 temas) cae al fallback que resuelve OMV→ATV.
    """
    cache_key = f"album_audio_resolved:{id}"
    if use_cache:
        cached = get_cached(cache_key)
        if cached is not None:
            return cached

    yt = _get_yt()
    resp = yt.browse(id)

    # 0) PRIMER INTENTO (RÁPIDO): watch-playlist de AUDIO completa, sembrada con 1er track
    apl_id = _album_audio_playlist_id(resp)
    seed_vid, seed_idx = _first_track_seed(resp)
    if apl_id:
        try:
            q_tracks = _fetch_full_audio_queue(yt, apl_id, seed_vid=seed_vid, seed_idx=seed_idx or 0)
            if q_tracks:
                out = {
                    "albumId": id,
                    "count": len(q_tracks),
                    "resolved": 0,
                    "tracks": q_tracks,
                    "unresolved": []
                }
                if use_cache: set_cached(cache_key, out, ttl=600)
                return out
        except Exception:
            pass  # si falla, seguimos con el fallback

    # 1) FALLBACK: parseo del álbum + resolución (paralela) — sólo si la queue no trajo nada
    album_artists = [a["name"] for a in _album_artists(resp)]
    album_name = _album_title(resp)

    tracks_raw, omv_candidates = [], []
    for mrlir in _iter_album_track_mrlir(resp):
        item = _map_album_track(mrlir)
        item["type"] = "audio" if _is_audio_track(mrlir) else "video"
        # ✔ garantiza thumbnails también acá
        if not item.get("thumbnails"):
            item["thumbnails"] = _thumbs_from_mrlir(mrlir, item.get("videoId"))
        tracks_raw.append(item)
        if item["type"] != "audio":
            omv_candidates.append(item)

    resolved = 0
    if try_resolve and omv_candidates:
        resolved = _resolve_omv_batch(
            omv_candidates[:max_resolve],
            album_artists,
            album_name,
            max_workers=8  # podés bajar a 4 si te da 429
        )

    def _idx(t):
        try: return int(t.get("index"))
        except: return 1_000_000
    tracks_raw.sort(key=_idx)

    out = {
        "albumId": id,
        "count": sum(1 for t in tracks_raw if t.get("type") == "audio"),
        "resolved": resolved,
        "tracks": [t for t in tracks_raw if t.get("type") == "audio"],
        "unresolved": [t for t in tracks_raw if t.get("type") != "audio"],
    }
    if use_cache: set_cached(cache_key, out, ttl=600)
    return out

@router.get("/new_releases_global")
def new_releases_global(use_cache: bool = Query(True, description="Usar cache")):
    """
    Devuelve la respuesta CRUDA del feed global de 'New releases'
    de YouTube Music (FEmusic_new_releases).
    Nada de parseos, exactamente lo que entrega Innertube.
    """
    cache_key = "new_releases_global"
    if use_cache:
        cached = get_cached(cache_key)
        if cached is not None:
            return cached

    try:
        yt = _get_yt()
        resp = yt.browse("FEmusic_new_releases")  # 🔴 feed global
        if use_cache:
            set_cached(cache_key, resp, ttl=600)
        return resp
    except Exception as e:
        return {"error": "new_releases_global_error", "detail": str(e)}

""" TESTING """

# --- NEW RELEASES (JSON crudo, región AR) ---
@router.get("/new_releases")
def new_releases():
    import re, requests

    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    })
    # evita pantalla de consentimiento y fija hl/gl en la página
    s.cookies.set("CONSENT", "YES+1")

    # 1) Bootstrap: leemos la home AR y extraemos API key, clientVersion y VISITOR_DATA
    resp = s.get("https://music.youtube.com/?hl=es&gl=AR&persist_hl=1&persist_gl=1", timeout=12)
    html = resp.text

    m_key = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', html) or re.search(r'"innertubeApiKey":"([^"]+)"', html)
    m_ver = re.search(r'"INNERTUBE_CONTEXT_CLIENT_VERSION":"([^"]+)"', html) or re.search(r'"clientVersion":"([^"]+)"', html)
    m_vis = re.search(r'"VISITOR_DATA":"([^"]+)"', html) or re.search(r'"visitorData":"([^"]+)"', html)
    if not (m_key and m_ver and m_vis):
        return {"error": "bootstrap_failed"}

    api_key     = m_key.group(1)
    client_ver  = m_ver.group(1)
    visitor_id  = m_vis.group(1)

    # 2) browse → pedimos el shelf de “Álbumes y sencillos” (no el mix)
    url = f"https://music.youtube.com/youtubei/v1/browse?key={api_key}"
    payload = {
        "context": {
            "client": {
                "clientName": "WEB_REMIX",
                "clientVersion": client_ver,
                "hl": "es",
                "gl": "AR",
                "utcOffsetMinutes": -180  # AR
            }
        },
        "browseId": "FEmusic_new_releases_albums"
    }
    headers = {
        "X-YouTube-Client-Name": "67",            # WEB_REMIX
        "X-YouTube-Client-Version": client_ver,
        "X-Goog-Visitor-Id": visitor_id
    }
    r = s.post(url, json=payload, headers=headers, timeout=12)
    r.raise_for_status()
    return r.json()
