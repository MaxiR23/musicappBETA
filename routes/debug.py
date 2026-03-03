# routes/debug.py
from fastapi import APIRouter, Query
from innertube import InnerTube
from services.cache_service import get_cached_legacy, set_cached_legacy
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from fastapi.responses import StreamingResponse, JSONResponse, RedirectResponse

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

def _ytmusic_client():
    # import lazy para no cargar ytmusicapi si no se usa
    from ytmusicapi import YTMusic
    return YTMusic()

## SEARCH DEBUG {

# =========================
# helpers TAB
# =========================
def _get_selected_tab(resp: dict):
    tabs = _dig(resp, ["contents", "tabbedSearchResultsRenderer", "tabs"], []) or []
    for t in tabs:
        tr = t.get("tabRenderer") or t.get("expandableTabRenderer")
        if tr and tr.get("selected"):
            return tr
    return None

# =========================
# helpers → MENU "Go to album/artist"
# =========================
def _extract_menu_navs(mrlir: dict) -> dict:
    """
    Devuelve ids navegables que aparecen en el menú contextual del item:
      {
        "album_id": "MPREb_...",
        "artist_id": "UCxxxx...",
        "albumItem": {...} | None,
        "artistItem": {...} | None
      }
    Soporta ES/EN: "Go to album/artist" / "Ir al álbum/artista".
    """
    items = _dig(mrlir, ["menu", "menuRenderer", "items"], []) or []
    out = {"album_id": None, "artist_id": None, "albumItem": None, "artistItem": None}

    def _txt(nir):
        return (_dig(nir, ["text", "runs", 0, "text"]) or "").strip().lower()

    for it in items:
        nir = it.get("menuNavigationItemRenderer")
        if not nir:
            continue
        txt = _txt(nir)
        be = _dig(nir, ["navigationEndpoint", "browseEndpoint"], {}) or {}
        bid = be.get("browseId")
        pgt = _dig(
            nir,
            [
                "navigationEndpoint",
                "browseEndpoint",
                "browseEndpointContextSupportedConfigs",
                "browseEndpointContextMusicConfig",
                "pageType",
            ],
        )

        # Album
        if (
            bid
            and pgt == "MUSIC_PAGE_TYPE_ALBUM"
            and (
                "go to album" in txt
                or "ir al álbum" in txt
                or "ir al album" in txt
                or txt == "album"
            )
        ):
            out["album_id"] = bid
            out["albumItem"] = nir

        # Artist
        if (
            bid
            and pgt == "MUSIC_PAGE_TYPE_ARTIST"
            and (
                "go to artist" in txt
                or "ir al artista" in txt
                or txt == "artist"
                or txt == "artista"
            )
        ):
            out["artist_id"] = bid
            out["artistItem"] = nir

    return out

# =========================
# ARTIST CARD → ARTIST INFO
# =========================
def parse_artist_card_info(resp: dict) -> dict | None:
    """
    Devuelve info del artista del Top result:
      - name
      - artist_id (browseId)
      - subtitle (string)
      - subtitleRuns (runs crudos)
      - subtitleTexts (lista de textos de los runs)
      - thumbnails
    """
    tab = _get_selected_tab(resp)
    if not tab:
        return None

    sections = _dig(tab, ["content", "sectionListRenderer", "contents"], []) or []
    if not sections:
        return None

    card = sections[0].get("musicCardShelfRenderer")
    if not card:
        return None

    # Confirmar que la card es de ARTISTA
    title_runs = _dig(card, ["title", "runs"], []) or []
    if not title_runs:
        return None
    nav = title_runs[0].get("navigationEndpoint", {})
    page_type = _dig(
        nav,
        [
            "browseEndpoint",
            "browseEndpointContextSupportedConfigs",
            "browseEndpointContextMusicConfig",
            "pageType",
        ],
    )
    if page_type != "MUSIC_PAGE_TYPE_ARTIST":
        return None

    name = title_runs[0].get("text", "")
    artist_id = _dig(nav, ["browseEndpoint", "browseId"])

    subtitle_runs = _dig(card, ["subtitle", "runs"], []) or []
    subtitle = "".join((r or {}).get("text", "") for r in subtitle_runs)
    subtitle_texts = [(r or {}).get("text", "") for r in subtitle_runs]

    thumbs = _dig(card, ["thumbnail", "musicThumbnailRenderer", "thumbnail", "thumbnails"], []) or []

    return {
        "name": name,
        "artist_id": artist_id,
        "subtitle": subtitle,            # ej: "Artist • 288M monthly audience"
        "subtitleRuns": subtitle_runs,   # runs crudos
        "subtitleTexts": subtitle_texts, # ["Artist", " • ", "288M monthly audience"]
        "thumbnails": thumbs,
        "type": "artist",
    }

# =========================
# ARTIST CARD → SONGS (Top result)
# =========================
def parse_artist_card_songs(resp: dict, strict_atv: bool = True, limit: int | None = None) -> list[dict]:
    out = []
    tab = _get_selected_tab(resp)
    if not tab:
        return out
    sections = _dig(tab, ["content", "sectionListRenderer", "contents"], []) or []
    if not sections:
        return out
    card = sections[0].get("musicCardShelfRenderer")
    if not card:
        return out

    title_runs = _dig(card, ["title", "runs"], []) or []
    nav = title_runs[0].get("navigationEndpoint", {}) if title_runs else {}
    page_type = _dig(
        nav,
        [
            "browseEndpoint",
            "browseEndpointContextSupportedConfigs",
            "browseEndpointContextMusicConfig",
            "pageType",
        ],
    )
    if page_type != "MUSIC_PAGE_TYPE_ARTIST":
        return out

    for it in card.get("contents", []):
        mrlir = it.get("musicResponsiveListItemRenderer")
        if not mrlir:
            continue

        links = _extract_menu_navs(mrlir)  # ← Go to album/artist

        item = extract_song_item(mrlir)
        if not item.get("videoId"):
            continue
        if strict_atv and item.get("musicVideoType") != "MUSIC_VIDEO_TYPE_ATV":
            continue
        out.append({
            "title": item.get("title"),
            "videoId": item.get("videoId"),
            "duration": item.get("duration"),
            "artists": item.get("artists", []),
            "thumbnails": item.get("thumbnails", []),
            "musicVideoType": item.get("musicVideoType"),
            "goTo": {                      # NUEVO
                "album_id": links["album_id"],
                "artist_id": links["artist_id"],
            },
        })
        if limit is not None and len(out) >= limit:
            break
    return out

# =========================
# ARTIST CARD → ALBUMS (Top result)
# =========================
def _is_album_item(mrlir: dict) -> bool:
    label = "".join((r or {}).get("text", "") for r in _runs(mrlir, 1)).strip().lower()
    if label.startswith("album"):
        return True
    page_type = _dig(
        mrlir,
        [
            "navigationEndpoint",
            "browseEndpoint",
            "browseEndpointContextSupportedConfigs",
            "browseEndpointContextMusicConfig",
            "pageType",
        ],
    )
    return page_type == "MUSIC_PAGE_TYPE_ALBUM"

def _extract_album_item(mrlir: dict) -> dict:
    title_runs = _runs(mrlir, 0)
    title = _dig(title_runs, [0, "text"]) or "".join((r or {}).get("text", "") for r in title_runs) or None
    album_browse_id = _dig(mrlir, ["navigationEndpoint", "browseEndpoint", "browseId"])
    playlist_id = _dig(
        mrlir,
        [
            "overlay",
            "musicItemThumbnailOverlayRenderer",
            "content",
            "musicPlayButtonRenderer",
            "playNavigationEndpoint",
            "watchPlaylistEndpoint",
            "playlistId",
        ],
    )
    artists = []
    for r in _runs(mrlir, 1):
        page_type = _dig(
            r,
            [
                "navigationEndpoint",
                "browseEndpoint",
                "browseEndpointContextSupportedConfigs",
                "browseEndpointContextMusicConfig",
                "pageType",
            ],
        )
        if page_type == "MUSIC_PAGE_TYPE_ARTIST":
            artists.append({"name": r.get("text", ""), "browseId": _dig(r, ["navigationEndpoint", "browseEndpoint", "browseId"])})

    year = None
    for r in reversed(_runs(mrlir, 1)):
        t = (r or {}).get("text", "").strip()
        if len(t) == 4 and t.isdigit():
            year = t
            break

    thumbs = _thumbs_from_mrlir(mrlir, None)
    links = _extract_menu_navs(mrlir)  # para goTo.artist_id

    return {
        "title": title,
        "album_id": album_browse_id,
        "playlistId": playlist_id,
        "artists": artists,
        "year": year,
        "thumbnails": thumbs,
        "type": "album",
        "goTo": {"artist_id": links["artist_id"]},  # NUEVO
    }

def parse_artist_card_albums(resp: dict, limit: int | None = None) -> list[dict]:
    out = []
    tab = _get_selected_tab(resp)
    if not tab:
        return out
    sections = _dig(tab, ["content", "sectionListRenderer", "contents"], []) or []
    if not sections:
        return out
    card = sections[0].get("musicCardShelfRenderer")
    if not card:
        return out
    title_runs = _dig(card, ["title", "runs"], []) or []
    nav = title_runs[0].get("navigationEndpoint", {}) if title_runs else {}
    page_type = _dig(
        nav,
        [
            "browseEndpoint",
            "browseEndpointContextSupportedConfigs",
            "browseEndpointContextMusicConfig",
            "pageType",
        ],
    )
    if page_type != "MUSIC_PAGE_TYPE_ARTIST":
        return out
    for it in card.get("contents", []):
        mrlir = it.get("musicResponsiveListItemRenderer")
        if not mrlir:
            continue
        if not _is_album_item(mrlir):
            continue
        item = _extract_album_item(mrlir)
        if not (item.get("album_id") or item.get("playlistId")):
            continue
        out.append(item)
        if limit is not None and len(out) >= limit:
            break
    return out

# =========================
# SEARCH (shelves generales) → ALBUMS + SONGS (solo música)
# =========================
def _mvtype_from_mrlir(mrlir: dict) -> str | None:
    return (
        _dig(
            mrlir,
            [
                "overlay",
                "musicItemThumbnailOverlayRenderer",
                "content",
                "musicPlayButtonRenderer",
                "playNavigationEndpoint",
                "watchEndpoint",
                "watchEndpointMusicSupportedConfigs",
                "watchEndpointMusicConfig",
                "musicVideoType",
            ],
        )
        or _dig(
            mrlir,
            [
                "flexColumns",
                0,
                "musicResponsiveListItemFlexColumnRenderer",
                "text",
                "runs",
                0,
                "navigationEndpoint",
                "watchEndpoint",
                "watchEndpointMusicSupportedConfigs",
                "watchEndpointMusicConfig",
                "musicVideoType",
            ],
        )
    )

def _is_episode_or_video(mrlir: dict) -> bool:
    # Si en la 2da col dice 'Episode/Episodio' o si el mvtype es OMV/UGC (video)
    col1 = "".join((r or {}).get("text", "") for r in _runs(mrlir, 1)).strip().lower()
    if "episode" in col1 or "episodio" in col1:
        return True
    mvtype = _mvtype_from_mrlir(mrlir)
    return mvtype in ("MUSIC_VIDEO_TYPE_OMV", "MUSIC_VIDEO_TYPE_UGC")

def _is_song_item_general(mrlir: dict) -> bool:
    """
    Más robusto para los shelves generales:
      - tiene watchEndpoint.videoId
      - mvtype == ATV
      - NO es álbum ni episodio
    """
    # no álbum
    label = "".join((r or {}).get("text", "") for r in _runs(mrlir, 1)).strip().lower()
    pt = _dig(
        mrlir,
        [
            "navigationEndpoint",
            "browseEndpoint",
            "browseEndpointContextSupportedConfigs",
            "browseEndpointContextMusicConfig",
            "pageType",
        ],
    )
    if label.startswith("album") or pt == "MUSIC_PAGE_TYPE_ALBUM":
        return False

    if _is_episode_or_video(mrlir):
        return False

    vid = (
        _dig(mrlir, ["playlistItemData", "videoId"])
        or _dig(mrlir, ["flexColumns", 0, "musicResponsiveListItemFlexColumnRenderer", "text", "runs", 0, "navigationEndpoint", "watchEndpoint", "videoId"])
        or _dig(mrlir, ["overlay", "musicItemThumbnailOverlayRenderer", "content", "musicPlayButtonRenderer", "playNavigationEndpoint", "watchEndpoint", "videoId"])
    )
    if not vid:
        return False

    mvtype = _mvtype_from_mrlir(mrlir)
    return mvtype == "MUSIC_VIDEO_TYPE_ATV"

def _extract_album_item_from_search(mrlir: dict) -> dict:
    title_runs = _runs(mrlir, 0)
    title = _dig(title_runs, [0, "text"]) or "".join((r or {}).get("text", "") for r in title_runs) or None
    album_browse_id = _dig(mrlir, ["navigationEndpoint", "browseEndpoint", "browseId"])
    playlist_id = _dig(
        mrlir,
        [
            "overlay",
            "musicItemThumbnailOverlayRenderer",
            "content",
            "musicPlayButtonRenderer",
            "playNavigationEndpoint",
            "watchPlaylistEndpoint",
            "playlistId",
        ],
    )
    artists = []
    for r in _runs(mrlir, 1):
        page_type = _dig(
            r,
            [
                "navigationEndpoint",
                "browseEndpoint",
                "browseEndpointContextSupportedConfigs",
                "browseEndpointContextMusicConfig",
                "pageType",
            ],
        )
        if page_type == "MUSIC_PAGE_TYPE_ARTIST":
            artists.append({"name": r.get("text", ""), "browseId": _dig(r, ["navigationEndpoint", "browseEndpoint", "browseId"])})

    year = None
    for r in reversed(_runs(mrlir, 1)):
        t = (r or {}).get("text", "").strip()
        if len(t) == 4 and t.isdigit():
            year = t
            break

    thumbs = _thumbs_from_mrlir(mrlir, None)
    links = _extract_menu_navs(mrlir)  # para goTo.artist_id

    return {
        "title": title,
        "album_id": album_browse_id,
        "playlistId": playlist_id,
        "artists": artists,
        "year": year,
        "thumbnails": thumbs,
        "type": "album",
        "goTo": {"artist_id": links["artist_id"]},  # NUEVO
    }

def parse_search_albums_and_songs(resp: dict, song_limit: int | None = None, album_limit: int | None = None) -> dict:
    songs, albums = [], []
    tab = _get_selected_tab(resp)
    if not tab:
        return {"songs": songs, "albums": albums}
    sections = _dig(tab, ["content", "sectionListRenderer", "contents"], []) or []
    for sec in sections:
        shelf = sec.get("musicShelfRenderer")
        if not shelf:
            continue
        for it in shelf.get("contents", []) or []:
            mrlir = it.get("musicResponsiveListItemRenderer")
            if not mrlir:
                continue

            # álbum
            label = "".join((r or {}).get("text", "") for r in _runs(mrlir, 1)).strip().lower()
            pt = _dig(
                mrlir,
                [
                    "navigationEndpoint",
                    "browseEndpoint",
                    "browseEndpointContextSupportedConfigs",
                    "browseEndpointContextMusicConfig",
                    "pageType",
                ],
            )
            if label.startswith("album") or pt == "MUSIC_PAGE_TYPE_ALBUM":
                album = _extract_album_item_from_search(mrlir)
                if album.get("album_id") or album.get("playlistId"):
                    albums.append(album)
                continue

            # canción (solo ATV)
            if _is_song_item_general(mrlir):
                links = _extract_menu_navs(mrlir)  # Go to album/artist
                s = extract_song_item(mrlir)
                if s.get("videoId"):
                    songs.append({
                        "title": s.get("title"),
                        "videoId": s.get("videoId"),
                        "artists": s.get("artists", []),
                        "thumbnails": s.get("thumbnails", []),
                        "musicVideoType": s.get("musicVideoType"),
                        "type": "song",
                        "goTo": {                # NUEVO
                            "album_id": links["album_id"],
                            "artist_id": links["artist_id"],
                        },
                    })

        # salida temprana si ya cumplimos ambos límites
        if (album_limit is not None and len(albums) >= album_limit) and (song_limit is not None and len(songs) >= song_limit):
            break

    if song_limit is not None:
        songs = songs[:song_limit]
    if album_limit is not None:
        albums = albums[:album_limit]
    return {"songs": songs, "albums": albums}

# =========================
# ENDPOINTS
# =========================

@router.get("/search_debug")
def search_debug(q: str = Query(..., description="Texto a buscar")):
    try:
        yt = _get_yt()
        response = yt.search(q)
        return response
    except Exception as e:
        return {"error": "search_error", "detail": str(e)}

@router.get("/search_debug_top")
def search_debug_top(q: str = Query(...)):
    """
    Debug: muestra el top result (musicCardShelfRenderer) con título, videoId,
    video_type, thumbnail y artistas con sus IDs.
    """
    try:
        yt = _get_yt()
        response = yt.search(q)

        shelves = (
            response.get("contents", {})
            .get("tabbedSearchResultsRenderer", {})
            .get("tabs", [])[0]
            .get("tabRenderer", {})
            .get("content", {})
            .get("sectionListRenderer", {})
            .get("contents", [])
        )

        card = next((c.get("musicCardShelfRenderer") for c in shelves if "musicCardShelfRenderer" in c), None)
        if not card:
            return {"ok": False, "message": "No hay musicCardShelfRenderer"}

        # --- título y videoId ---
        title_block = card.get("title", {}).get("runs", [{}])[0]
        title_text = title_block.get("text")
        watch = title_block.get("navigationEndpoint", {}).get("watchEndpoint", {})
        video_id = watch.get("videoId")
        video_type = (
            watch.get("watchEndpointMusicSupportedConfigs", {})
            .get("watchEndpointMusicConfig", {})
            .get("musicVideoType")
        )

        # --- artistas (nombre + browseId) ---
        artists = []
        subtitle_runs = card.get("subtitle", {}).get("runs", [])
        for run in subtitle_runs:
            nav = run.get("navigationEndpoint", {}).get("browseEndpoint", {})
            browse_id = nav.get("browseId")
            name = run.get("text")
            if browse_id and name:
                artists.append({"name": name, "id": browse_id})

        # --- duración ---
        duration = None
        for run in subtitle_runs:
            if ":" in run.get("text", ""):
                duration = run["text"]
                break

        # --- thumbnail ---
        thumbs = (
            card.get("thumbnail", {})
            .get("musicThumbnailRenderer", {})
            .get("thumbnail", {})
            .get("thumbnails", [])
        )
        thumb = thumbs[-1]["url"] if thumbs else None

        return {
            "ok": True,
            "query": q,
            "title": title_text,
            "videoId": video_id,
            "video_type": video_type,
            "artists": artists,
            "duration": duration,
            "thumbnail_url": thumb,
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}

@router.get("/search_debug_song")
def search_debug_song(q: str = Query(...)):
    """
    1️⃣ Si el Top Result (musicCardShelfRenderer) es ATV, lo devuelve.
    2️⃣ Si no, cae al shelf 'Songs'.
    """
    try:
        yt = _get_yt()
        response = yt.search(q)

        # obtener shelves principales
        shelves = (
            response.get("contents", {})
            .get("tabbedSearchResultsRenderer", {})
            .get("tabs", [])[0]
            .get("tabRenderer", {})
            .get("content", {})
            .get("sectionListRenderer", {})
            .get("contents", [])
        )

        # =============================
        # 1️⃣ TOP RESULT (CardShelf)
        # =============================
        card = next((c.get("musicCardShelfRenderer") for c in shelves if "musicCardShelfRenderer" in c), None)
        if card:
            title_block = card.get("title", {}).get("runs", [{}])[0]
            title_text = title_block.get("text")
            watch = title_block.get("navigationEndpoint", {}).get("watchEndpoint", {})
            video_id = watch.get("videoId")
            video_type = (
                watch.get("watchEndpointMusicSupportedConfigs", {})
                .get("watchEndpointMusicConfig", {})
                .get("musicVideoType")
            )

            # ✅ si el top result es ATV → devolver este
            if video_type == "MUSIC_VIDEO_TYPE_ATV":
                # artistas
                artists = []
                subtitle_runs = card.get("subtitle", {}).get("runs", [])
                for run in subtitle_runs:
                    nav = run.get("navigationEndpoint", {}).get("browseEndpoint", {})
                    browse_id = nav.get("browseId")
                    name = run.get("text")
                    if browse_id and name:
                        artists.append({"name": name, "id": browse_id})

                # duración
                duration = None
                for run in subtitle_runs:
                    if ":" in run.get("text", ""):
                        duration = run["text"]
                        break

                # thumbnail
                thumbs = (
                    card.get("thumbnail", {})
                    .get("musicThumbnailRenderer", {})
                    .get("thumbnail", {})
                    .get("thumbnails", [])
                )
                thumb = thumbs[-1]["url"] if thumbs else None

                return {
                    "ok": True,
                    "source": "TopResult",
                    "query": q,
                    "song": {
                        "title": title_text,
                        "videoId": video_id,
                        "video_type": video_type,
                        "artists": artists,
                        "duration": duration,
                        "thumbnail_url": thumb,
                    },
                }

        # =============================
        # 2️⃣ FALLBACK → SONGS (no tocar)
        # =============================
        songs_shelf = next(
            (c["musicShelfRenderer"] for c in shelves if "musicShelfRenderer" in c),
            None,
        )
        if not songs_shelf:
            return {"ok": False, "message": "No se encontró shelf Songs"}

        contents = songs_shelf.get("contents", [])
        if not contents:
            return {"ok": False, "message": "Shelf Songs vacío"}

        r = contents[0].get("musicResponsiveListItemRenderer", {})
        if not r:
            return {"ok": False, "message": "No se encontró renderer en Songs[0]"}

        # --- título e ID del video ---
        title_run = (
            r.get("flexColumns", [{}])[0]
            .get("musicResponsiveListItemFlexColumnRenderer", {})
            .get("text", {})
            .get("runs", [{}])[0]
        )
        title = title_run.get("text")
        video_id = (
            title_run.get("navigationEndpoint", {})
            .get("watchEndpoint", {})
            .get("videoId")
        )

        # --- artista y su ID ---
        artist_runs = (
            r.get("flexColumns", [{}])[1]
            .get("musicResponsiveListItemFlexColumnRenderer", {})
            .get("text", {})
            .get("runs", [])
        )
        artist_name = None
        artist_id = None
        for run in artist_runs:
            if "browseEndpoint" in run.get("navigationEndpoint", {}):
                artist_name = run.get("text")
                artist_id = run["navigationEndpoint"]["browseEndpoint"].get("browseId")
                break

        # --- thumbnail ---
        thumbs = (
            r.get("thumbnail", {})
            .get("musicThumbnailRenderer", {})
            .get("thumbnail", {})
            .get("thumbnails", [])
        )
        thumbnail_url = thumbs[-1]["url"] if thumbs else None

        return {
            "ok": True,
            "source": "Songs",
            "query": q,
            "song": {
                "title": title,
                "videoId": video_id,
                "artist_name": artist_name,
                "artist_id": artist_id,
                "thumbnail_url": thumbnail_url,
            },
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}

@router.get("/search_debug_improved_version")
def search_debug_improved_version(
    q: str = Query(..., description="Texto a buscar"),
    limit: int = Query(5, ge=1, le=20),                      # artist card songs
    strict_atv: bool = Query(True, description="Filtra MUSIC_VIDEO_TYPE_ATV"),
    include_albums: bool = Query(True),                      # artist card albums
    album_limit: int = Query(5, ge=1, le=20),
    include_search: bool = Query(True, description="Incluir resultados generales (albums + songs)"),
    search_song_limit: int = Query(10, ge=1, le=50),
    search_album_limit: int = Query(10, ge=1, le=50),
):
    """
    Respuesta en este orden:
      - artist  : { name, artist_id, subtitle, subtitleRuns, subtitleTexts, thumbnails }
      - songs   : (artist card) [{ title, videoId, duration, artists, thumbnails, musicVideoType, goTo{album_id,artist_id} }]
      - albums  : (artist card) [{ title, album_id, playlistId, artists, year, thumbnails, goTo{artist_id} }]
      - search  : (generales) {
                     songs : [{ ...ATV only..., goTo{album_id,artist_id} }],
                     albums: [{ ..., goTo{artist_id} }]
                   }
    """
    try:
        yt = _get_yt()
        resp = yt.search(q)

        artist = parse_artist_card_info(resp)
        songs  = parse_artist_card_songs(resp, strict_atv=strict_atv, limit=limit)
        albums = parse_artist_card_albums(resp, limit=album_limit) if include_albums else []
        search_out = parse_search_albums_and_songs(
            resp, song_limit=search_song_limit, album_limit=search_album_limit
        ) if include_search else {"songs": [], "albums": []}

        return {
            "success": True,
            "message": (
                f"Artist card: artist={'yes' if bool(artist) else 'no'}, "
                f"songs={len(songs)}, albums={len(albums)}; "
                f"Search: songs={len(search_out['songs'])}, albums={len(search_out['albums'])}"
            ),
            "data": {
                "query": q,
                "artist": artist,
                "songs": songs,
                "albums": albums,
                "search": search_out,
            },
        }
    except Exception as e:
        return {
            "success": False,
            "message": "search_error",
            "data": {"query": q, "error": str(e)},
        }

## SEARCH DEBUG }






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

        return {"artist_id": id, "contents": contents}

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
    cached = get_cached_legacy(key)
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

    set_cached_legacy(key, best, ttl=cache_ttl)
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
        cached = get_cached_legacy(cache_key)
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
                    "album_id": id,
                    "count": len(q_tracks),
                    "resolved": 0,
                    "tracks": q_tracks,
                    "unresolved": []
                }
                if use_cache: set_cached_legacy(cache_key, out, ttl=600)
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
        "album_id": id,
        "count": sum(1 for t in tracks_raw if t.get("type") == "audio"),
        "resolved": resolved,
        "tracks": [t for t in tracks_raw if t.get("type") == "audio"],
        "unresolved": [t for t in tracks_raw if t.get("type") != "audio"],
    }
    if use_cache: set_cached_legacy(cache_key, out, ttl=600)
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
        cached = get_cached_legacy(cache_key)
        if cached is not None:
            return cached

    try:
        yt = _get_yt()
        resp = yt.browse("FEmusic_new_releases")  # 🔴 feed global
        if use_cache:
            set_cached_legacy(cache_key, resp, ttl=600)
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

@router.get("/album/ytmusicapi")
def debug_album_ytmusicapi(
    id: str | None = Query(None, description="Album browseId MPRE…"),
    apl: str | None = Query(None, description="audio_playlist_id OLAK5…"),
    raw: int | None = Query(0, description="Si raw=1, devuelve TODO sin filtrar"),
):
    """
    Devuelve el tracklist ATV de un álbum o audio-playlist.
    - Si viene apl=OLAK5…, usa esa audio-playlist (get_playlist).
    - Si no, usa id=MPRE… → get_album → audio_playlist_id → get_playlist.
    - Si raw=1, devuelve TODO lo que traen las llamadas de ytmusicapi (sin filtrar).
    Cambios pedidos:
      • Removido "artists" del objeto "album".
      • Un solo "thumbnail" por track: el más grande disponible.
    """
    try:
        from fastapi import HTTPException
        from fastapi.responses import JSONResponse
        from ytmusicapi import YTMusic

        def _sec(x):
            if isinstance(x, int): return x
            s = (x or "").strip()
            if not s: return None
            p = [int(v) for v in s.split(":")]
            if len(p)==3: return p[0]*3600+p[1]*60+p[2]
            if len(p)==2: return p[0]*60+p[1]
            try: return int(s)
            except: return None

        def biggest_thumb_url(thumbs):
            """Devuelve la URL del thumbnail más grande posible."""
            if not thumbs:
                return None
            # Algunos items traen width/height, otros solo URL con w/h en query;
            # priorizamos por 'width' si existe, si no, nos quedamos con el último.
            with_size = [t for t in thumbs if isinstance(t, dict) and t.get("width")]
            if with_size:
                return max(with_size, key=lambda t: (t.get("width", 0), t.get("height", 0))).get("url")
            return thumbs[-1].get("url") if isinstance(thumbs[-1], dict) else None

        ytm = YTMusic()

        # === Resolver APL (OLAK5…) ===
        album_title = None
        if apl:
            apl_id = apl
        elif id:
            alb = ytm.get_album(id)
            apl_id = alb.get("audio_playlist_id")
            if not apl_id:
                raise HTTPException(status_code=404, detail={
                    "error": "no_audio_playlist",
                    "message": "El álbum no expone audio_playlist_id (OLAK5…).",
                    "album_browseId": id
                })
            album_title = alb.get("title")
        else:
            raise HTTPException(status_code=400, detail={
                "error": "missing_params",
                "message": "Pasá apl=OLAK5… o id=MPRE…"
            })

        # === Llamadas crudas ===
        pl_meta  = ytm.get_playlist(apl_id) or {}
        pl_watch = ytm.get_watch_playlist(playlistId=apl_id) or {}

        # === RAW MODE ===
        if raw:
            return JSONResponse(
                content={
                    "params": {"id": id, "apl": apl_id, "raw": raw},
                    "get_playlist": pl_meta,
                    "get_watch_playlist": pl_watch,
                },
                media_type="application/json"
            )

        # === Resumen normal ===
        pl_title  = pl_meta.get("title") or pl_watch.get("title") or album_title or ""
        pl_tracks = pl_meta.get("tracks") or []

        # Map de salida (un solo "thumbnail" = el más grande)
        out_tracks = []
        for i, t in enumerate(pl_tracks, 1):
            title     = t.get("title")
            vid       = t.get("videoId")
            dur_txt   = t.get("duration") or ""
            dur_s     = t.get("duration_seconds") or _sec(dur_txt)
            artists   = t.get("artists") or []
            first_art = artists[0] if artists else {}
            album     = t.get("album") or {}
            thumbs    = t.get("thumbnails") or []
            thumb_big = biggest_thumb_url(thumbs)

            out_tracks.append({
                "index": i,
                "title": title,
                "duration": dur_txt,
                "duration_seconds": dur_s,
                "videoId": vid,
                "musicVideoType": t.get("videoType", "MUSIC_VIDEO_TYPE_ATV"),
                "artist": first_art.get("name"),
                "artist_id": first_art.get("id"),
                "album": album.get("name"),
                "album_id": album.get("id"),
                "thumbnail": thumb_big,
                "urls": {
                    "watch": f"https://music.youtube.com/watch?v={vid}" if vid else None,
                    "watch_in_album": (f"https://music.youtube.com/watch?v={vid}&list={apl_id}"
                                       if vid else None),
                },
            })

        return {
            "selected": (
                {"browseId": id, "title": album_title or pl_title}
                if id else {"browseId": apl_id, "title": pl_title}
            ),
            "album": {
                "title": album_title or pl_title,
                # ← pedido: SIN 'artists' en 'album'
                "tracks_count": len(out_tracks),
                "audio_playlist_id": apl_id,
                "audioPlaylistTitle": pl_title,
                "tracks": out_tracks,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail={
            "error": "ytmusicapi_album_or_apl_error",
            "message": str(e),
            "params": {"id": id, "apl": apl, "raw": raw}
        })

@router.get("/debug_artist_info")
def debug_artist_info(id: str = Query(...)):
    """Debug: muestra TODO lo que trae ytmusicapi.get_artist() sin filtros"""
    try:
        yt = _ytmusic_client()
        artist_data = yt.get_artist(id)
        
        # Obtener top 10 songs
        songs_browse_id = artist_data.get("songs", {}).get("browseId")
        top_songs_raw = []
        if songs_browse_id:
            playlist_data = yt.get_playlist(songs_browse_id, limit=10)
            top_songs_raw = (playlist_data.get("tracks", []))[:10]
        
        # Filtrar solo campos necesarios
        top_songs_filtered = []
        for track in top_songs_raw:
            # Artists
            artists_list = track.get("artists", [])
            artists = [{"id": a.get("id"), "name": a.get("name")} for a in artists_list]
            artist_name = ", ".join(a["name"] for a in artists if a.get("name"))
            primary_artist_id = artists[0]["id"] if artists else None
            
            # Album
            album = track.get("album") or {}
            album_id = album.get("id")
            album_title = album.get("name")
            
            # Thumbnail
            thumbs = track.get("thumbnails", [])
            thumbnail = thumbs[-1]["url"] if thumbs else None
            
            top_songs_filtered.append({
                "id": track.get("videoId"),
                "title": track.get("title"),
                "thumbnail": thumbnail,
                "album_id": album_id,
                "albumTitle": album_title,
                "artist_id": primary_artist_id,
                "artist_name": artist_name,
                "artists": artists,
                "duration": track.get("duration"),
                "duration_seconds": track.get("duration_seconds")
            })
        
        return {
            "artist_id": id,
            "raw_data": artist_data,
            "top_10_songs": top_songs_filtered
        }
    except Exception as e:
        import traceback
        return JSONResponse(status_code=500, content={
            "error": str(e),
            "traceback": traceback.format_exc()
        })
    
@router.get("/debug_artist_albums")
def debug_artist_albums(id: str = Query(...)):
    """Debug: trae TODOS los albums de un artista"""
    try:
        yt = _ytmusic_client()
        artist_data = yt.get_artist(id)
        
        # Obtener TODOS los albums
        albums_section = artist_data.get("albums", {})
        albums_browse_id = albums_section.get("browseId")
        albums_params = albums_section.get("params")
        
        all_albums_raw = []
        if albums_browse_id:
            all_albums_raw = yt.get_artist_albums(albums_browse_id, albums_params)
        
        return {
            "artist_id": id,
            "total_albums": len(all_albums_raw),
            "all_albums_raw": all_albums_raw
        }
    except Exception as e:
        import traceback
        return JSONResponse(status_code=500, content={
            "error": str(e),
            "traceback": traceback.format_exc()
        })
    
@router.get("/debug_artist_singles")
def debug_artist_singles(id: str = Query(...)):
    """Debug: trae TODOS los singles/EPs de un artista"""
    try:
        yt = _ytmusic_client()
        artist_data = yt.get_artist(id)
        
        # Obtener TODOS los singles
        singles_section = artist_data.get("singles", {})
        singles_browse_id = singles_section.get("browseId")
        singles_params = singles_section.get("params")
        
        all_singles_raw = []
        if singles_browse_id:
            all_singles_raw = yt.get_artist_albums(singles_browse_id, singles_params)
        
        return {
            "artist_id": id,
            "total_singles": len(all_singles_raw),
            "all_singles_raw": all_singles_raw
        }
    except Exception as e:
        import traceback
        return JSONResponse(status_code=500, content={
            "error": str(e),
            "traceback": traceback.format_exc()
        })
    
@router.get("/debug_artist_single_raw")
def debug_artist_single_raw(id: str = Query(...)):
    """Debug: TODO CRUDO COMPLETO"""
    try:
        yt = _ytmusic_client()
        artist_data = yt.get_artist(id)
        
        singles_section = artist_data.get("singles")
        
        return {
            "singles_section_completa": singles_section,
            "artist_data_completo": artist_data
        }
        
    except Exception as e:
        import traceback
        return JSONResponse(status_code=500, content={
            "error": str(e),
            "traceback": traceback.format_exc()
        })
    
""" TESTING SEARCH YTMUSICAPI { """    

@router.get("/search_ytmusicapi_debug")
def search_ytmusicapi_debug(q: str = Query(..., description="Texto a buscar")):
    """
    Debug: search usando ytmusicapi en vez de InnerTube.
    Devuelve TODO crudo sin filtrar para ver qué campos vienen.
    """
    try:
        yt = _ytmusic_client()
        results = yt.search(q)
        
        return {
            "query": q,
            "total_results": len(results),
            "results": results
        }
    except Exception as e:
        import traceback
        return JSONResponse(status_code=500, content={
            "error": str(e),
            "traceback": traceback.format_exc()
        })
    
""" TESTING SEARCH YTMUSICAPI } """    

""" TESTING GETTING ALBUM NAME { """

@router.get("/album_name_only")
def album_name_only(album_id: str = Query(..., description="Album browseId")):
    """
    Extrae SOLO el nombre del álbum, sin parsear tracks.
    Rápido y liviano.
    """
    try:
        yt = _get_yt()
        response = yt.browse(album_id)
        
        # Path correcto basado en la imagen
        title = _dig(response, [
            "contents", "twoColumnBrowseResultsRenderer", "tabs", 0, 
            "tabRenderer", "content", "sectionListRenderer", "contents", 0,
            "musicResponsiveHeaderRenderer", "title", "runs", 0, "text"
        ])
        
        return {
            "album_id": album_id,
            "album_name": title,
            "success": title is not None
        }
    except Exception as e:
        import traceback
        return {
            "album_id": album_id,
            "album_name": None,
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }

""" TESTING GETTING ALBUM NAME } """

""" TESTING GETTING SONG DURATION { """

@router.get("/song_duration_debug")
def song_duration_debug(video_id: str = Query(..., description="videoId de la canción")):
    """
    Debug: obtener SOLO la duración de una canción por videoId.
    Ver qué trae ytmusicapi.get_song()
    """
    try:
        yt = _ytmusic_client()
        song_info = yt.get_song(video_id)
        
        return {
            "videoId": video_id,
            "full_response": song_info,
            "success": True
        }
    except Exception as e:
        import traceback
        return {
            "videoId": video_id,
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


@router.get("/song_duration_only")
def song_duration_only(video_id: str = Query(..., description="videoId de la canción")):
    """
    Debug: Extrae SOLO la duración de una canción.
    Rápido y liviano, sin traer toda la data.
    """
    try:
        yt = _ytmusic_client()
        song_info = yt.get_song(video_id)
        
        # Extraer SOLO lengthSeconds
        duration_seconds = song_info.get("videoDetails", {}).get("lengthSeconds")
        
        if duration_seconds:
            duration_seconds = int(duration_seconds)
            minutes = duration_seconds // 60
            seconds = duration_seconds % 60
            duration_secondstr = f"{minutes}:{seconds:02d}"
            
            return {
                "videoId": video_id,
                "duration": duration_secondstr,
                "duration_seconds": duration_seconds,
                "success": True
            }
        else:
            return {
                "videoId": video_id,
                "duration": None,
                "success": False,
                "error": "No lengthSeconds found"
            }
    except Exception as e:
        import traceback
        return {
            "videoId": video_id,
            "duration": None,
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }

""" TESTING GETTING SONG DURATION } """