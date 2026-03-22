# utils/search_parser.py
import re

# ---------- CACHE para enriquecimiento de datos ----------
_ALBUM_NAME_CACHE = {}
_DURATION_CACHE = {}

def _get_album_name_fast(yt_innertube, album_id: str) -> str | None:
    """Extrae SOLO el nombre del álbum sin parsear tracks (usa InnerTube)"""
    if album_id in _ALBUM_NAME_CACHE:
        return _ALBUM_NAME_CACHE[album_id]
    
    try:
        response = yt_innertube.browse(album_id)
        title = _dig(response, [
            "contents", "twoColumnBrowseResultsRenderer", "tabs", 0, 
            "tabRenderer", "content", "sectionListRenderer", "contents", 0,
            "musicResponsiveHeaderRenderer", "title", "runs", 0, "text"
        ])
        _ALBUM_NAME_CACHE[album_id] = title
        return title
    except:
        return None

def _get_duration_fast(yt_api, video_id: str) -> tuple[str | None, int | None]:
    """Devuelve (duration_str, duration_seconds) usando ytmusicapi."""
    if video_id in _DURATION_CACHE:
        return _DURATION_CACHE[video_id]

    try:
        song_info = yt_api.get_song(video_id)
        seconds = song_info.get("videoDetails", {}).get("lengthSeconds")
        if seconds:
            seconds = int(seconds)
            minutes = seconds // 60
            sec = seconds % 60
            duration_str = f"{minutes}:{sec:02d}"
            _DURATION_CACHE[video_id] = (duration_str, seconds)
            return duration_str, seconds
    except:
        pass

    _DURATION_CACHE[video_id] = (None, None)
    return None, None

def _enrich_songs_with_metadata(yt_innertube, yt_api, songs: list[dict]):
    """Enriquece canciones con album_name y duration si no las tienen"""
    for song in songs:
        # Album name (usa InnerTube)
        album_id = song.get("go_to", {}).get("album_id")
        if album_id and not song.get("album_name"):
            song["album_name"] = _get_album_name_fast(yt_innertube, album_id)
        
        # Duration (usa ytmusicapi)
        track_id = song.get("track_id")
        if track_id and not song.get("duration_seconds"):
            dstr, dsec = _get_duration_fast(yt_api, track_id)
            if dstr and not song.get("duration"):
                song["duration"] = dstr
            if dsec:
                song["duration_seconds"] = dsec

# ---------- helpers básicos ----------
def _dig(cur, path, default=None):
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

def _runs_text(runs): return "".join((r or {}).get("text", "") for r in (runs or []))
def _runs(mrlir, col_idx):
    return _dig(mrlir, ["flexColumns", col_idx, "musicResponsiveListItemFlexColumnRenderer", "text", "runs"], []) or []

def _get_selected_tab(resp: dict):
    tabs = _dig(resp, ["contents", "tabbedSearchResultsRenderer", "tabs"], []) or []
    for t in tabs:
        tr = t.get("tabRenderer") or t.get("expandableTabRenderer")
        if tr and tr.get("selected"): return tr
    return None

def _is_songs_shelf(shelf: dict) -> bool:
    return _runs_text(_dig(shelf, ["title", "runs"], [])).strip().lower() in ("songs", "canciones")

# ---------- helpers compactos comunes ----------
def _page_type_from(node) -> str | None:
    return _dig(node, [
        "navigationEndpoint","browseEndpoint",
        "browseEndpointContextSupportedConfigs","browseEndpointContextMusicConfig","pageType"
    ])

def _video_id(mrlir) -> str | None:
    return (
        _dig(mrlir, ["playlistItemData", "videoId"]) or
        _dig(mrlir, ["flexColumns",0,"musicResponsiveListItemFlexColumnRenderer","text","runs",0,"navigationEndpoint","watchEndpoint","videoId"]) or
        _dig(mrlir, ["overlay","musicItemThumbnailOverlayRenderer","content","musicPlayButtonRenderer","playNavigationEndpoint","watchEndpoint","videoId"])
    )

def _mvtype(mrlir) -> str | None:
    return (
        _dig(mrlir, [
            "overlay","musicItemThumbnailOverlayRenderer","content","musicPlayButtonRenderer",
            "playNavigationEndpoint","watchEndpoint","watchEndpointMusicSupportedConfigs",
            "watchEndpointMusicConfig","musicVideoType"
        ]) or
        _dig(mrlir, [
            "flexColumns",0,"musicResponsiveListItemFlexColumnRenderer","text","runs",0,
            "navigationEndpoint","watchEndpoint","watchEndpointMusicSupportedConfigs",
            "watchEndpointMusicConfig","musicVideoType"
        ])
    )

def _is_album_row(mrlir) -> bool:
    # por label o por pageType
    label = _runs_text(_runs(mrlir, 1)).strip().lower()
    if label.startswith("album"): return True
    return _page_type_from(mrlir) == "MUSIC_PAGE_TYPE_ALBUM"

def _is_episode_or_video_row(mrlir) -> bool:
    # 1) texto "episode/episodio"
    col1 = _runs_text(_runs(mrlir, 1)).strip().lower()
    if "episode" in col1 or "episodio" in col1: return True
    # 2) mvtype de video no-musical
    return _mvtype(mrlir) in ("MUSIC_VIDEO_TYPE_OMV", "MUSIC_VIDEO_TYPE_UGC")

def _is_atv_song_row(mrlir) -> bool:
    # canción válida: tiene videoId, mvtype ATV y no es álbum ni episodio
    if _is_album_row(mrlir) or _is_episode_or_video_row(mrlir):
        return False
    vid = _video_id(mrlir)
    return bool(vid) and _mvtype(mrlir) == "MUSIC_VIDEO_TYPE_ATV"

def _parse_duration(info_runs, accessibility_label):
    # 1) "mm:ss" o "h:mm:ss" en runs
    for r in reversed(info_runs or []):
        txt = (r or {}).get("text", "")
        parts = txt.split(":")
        if len(parts) in (2,3) and all(p.isdigit() for p in parts): return txt
    # 2) "3 minutes, 32 seconds"
    if accessibility_label:
        m = re.search(r"(?:(\d+)\s+hours?,\s*)?(?:(\d+)\s+minutes?,\s*)?(\d+)\s+seconds?", accessibility_label)
        if m:
            h = int(m.group(1) or 0); mnt = int(m.group(2) or 0); sec = int(m.group(3) or 0)
            total = h*3600 + mnt*60 + sec
            if total >= 3600:
                hh = total // 3600; mm = (total % 3600)//60; ss = total % 60
                return f"{hh}:{mm:02d}:{ss:02d}"
            else:
                mm = total // 60; ss = total % 60
                return f"{mm}:{ss:02d}"
    return None

def _extract_menu_navs(mrlir: dict) -> dict:
    items = _dig(mrlir, ["menu", "menuRenderer", "items"], []) or []
    out = {"album_id": None, "artist_id": None, "album_item": None, "artist_item": None}
    def _txt(nir): return (_dig(nir, ["text","runs",0,"text"]) or "").strip().lower()
    for it in items:
        nir = it.get("menuNavigationItemRenderer"); 
        if not nir: continue
        txt = _txt(nir)
        be = _dig(nir, ["navigationEndpoint","browseEndpoint"], {}) or {}
        bid = be.get("browseId")
        pgt = _page_type_from(nir)
        if bid and pgt == "MUSIC_PAGE_TYPE_ALBUM" and ( "go to album" in txt or "ir al álbum" in txt or "ir al album" in txt or txt == "album" ):
            out["album_id"], out["album_item"] = bid, nir
        if bid and pgt == "MUSIC_PAGE_TYPE_ARTIST" and ( "go to artist" in txt or "ir al artista" in txt or txt in ("artist","artista") ):
            out["artist_id"], out["artist_item"] = bid, nir
    return out

# ---------- extracción de SONG ----------
def _extract_song_item(mrlir: dict) -> dict:
    title_runs = _runs(mrlir, 0)
    info_runs  = _runs(mrlir, 1)

    title = _dig(title_runs, [0,"text"]) or _runs_text(title_runs) or None

    artists = []
    for r in info_runs:
        if _page_type_from(r) == "MUSIC_PAGE_TYPE_ARTIST":
            artists.append({"name": r.get("text",""), "artist_id": _dig(r,["navigationEndpoint","browseEndpoint","browseId"])})

    album = None
    for r in info_runs:
        if _page_type_from(r) == "MUSIC_PAGE_TYPE_ALBUM":
            album = {"name": r.get("text",""), "album_id": _dig(r,["navigationEndpoint","browseEndpoint","browseId"])}
            break

    duration = _parse_duration(info_runs, _dig(mrlir, ["accessibility","accessibilityData","label"]))
    thumbs = _dig(mrlir, ["thumbnail","musicThumbnailRenderer","thumbnail","thumbnails"], []) or []

    return {
        "title": title,
        "artists": artists,
        "album": album,
        "duration": duration,
        "track_id": _video_id(mrlir),
        "thumbnails": thumbs,
        "title_runs": title_runs,
        "info_runs": info_runs,
    }

# ---------- SONGS shelf (con duración) ----------
def parse_search_songs(resp: dict, strict_atv: bool = True) -> list[dict]:
    out = []
    tab = _get_selected_tab(resp)
    if not tab: return out
    sections = _dig(tab, ["content","sectionListRenderer","contents"], []) or []
    for sec in sections:
        shelf = sec.get("musicShelfRenderer")
        if not shelf or not _is_songs_shelf(shelf): continue
        for it in shelf.get("contents", []) or []:
            mrlir = it.get("musicResponsiveListItemRenderer"); 
            if not mrlir: continue
            if not _is_atv_song_row(mrlir): continue
            item = _extract_song_item(mrlir)
            if not item.get("track_id"): continue
            if strict_atv and item.get("music_video_type") != "MUSIC_VIDEO_TYPE_ATV": continue
            out.append(item)
        break
    return out

# ---------- ARTIST CARD → ARTIST INFO ----------
def parse_artist_card_info(resp: dict) -> dict | None:
    tab = _get_selected_tab(resp)
    if not tab: return None
    sections = _dig(tab, ["content","sectionListRenderer","contents"], []) or []
    if not sections: return None
    card = None
    for sec in sections:
        if "musicCardShelfRenderer" in sec:
            card = sec["musicCardShelfRenderer"]
            break
    if not card: return None

    title_runs = _dig(card, ["title","runs"], []) or []
    if not title_runs: return None
    nav = title_runs[0].get("navigationEndpoint", {}) or {}
    if _dig(nav, [
        "browseEndpoint","browseEndpointContextSupportedConfigs",
        "browseEndpointContextMusicConfig","pageType"
    ]) != "MUSIC_PAGE_TYPE_ARTIST":
        return None

    name = title_runs[0].get("text","")
    artist_id = _dig(nav, ["browseEndpoint","browseId"])
    subtitle_runs = _dig(card, ["subtitle","runs"], []) or []
    subtitle = _runs_text(subtitle_runs)
    subtitle_texts = [(r or {}).get("text","") for r in subtitle_runs]
    thumbs = _dig(card, ["thumbnail","musicThumbnailRenderer","thumbnail","thumbnails"], []) or []

    return {
        "name": name,
        "artist_id": artist_id,
        "subtitle": subtitle,
        "subtitle_runs": subtitle_runs,
        "subtitle_texts": subtitle_texts,
        "thumbnails": thumbs,
        "type": "artist",
    }

# ---------- ARTIST CARD → SONGS (sin duración) ----------
def parse_artist_card_songs(resp: dict, strict_atv: bool = True, limit: int | None = None, yt_innertube=None, yt_api=None, enrich_metadata: bool = False) -> list[dict]:
    out = []
    tab = _get_selected_tab(resp)
    if not tab: return out
    sections = _dig(tab, ["content","sectionListRenderer","contents"], []) or []
    if not sections: return out
    card = None
    for sec in sections:
        if "musicCardShelfRenderer" in sec:
            card = sec["musicCardShelfRenderer"]
            break
    if not card: return out

    title_runs = _dig(card, ["title","runs"], []) or []
    nav = title_runs[0].get("navigationEndpoint", {}) if title_runs else {}
    if _dig(nav, [
        "browseEndpoint","browseEndpointContextSupportedConfigs",
        "browseEndpointContextMusicConfig","pageType"
    ]) != "MUSIC_PAGE_TYPE_ARTIST":
        return out

    for it in card.get("contents", []) or []:
        mrlir = it.get("musicResponsiveListItemRenderer"); 
        if not mrlir: continue
        if not _is_atv_song_row(mrlir): continue

        links = _extract_menu_navs(mrlir)
        s = _extract_song_item(mrlir)
        if not s.get("track_id"): continue
        if strict_atv and s.get("music_video_type") != "MUSIC_VIDEO_TYPE_ATV": continue

        out.append({
            "title": s.get("title"),
            "track_id": s.get("track_id"),
            "artists": s.get("artists", []),
            "thumbnails": s.get("thumbnails", []),
            "go_to": {"album_id": links["album_id"], "artist_id": links["artist_id"]},
        })
        if limit is not None and len(out) >= limit: break
    
    if enrich_metadata and yt_innertube and yt_api:
        _enrich_songs_with_metadata(yt_innertube, yt_api, out)
    
    return out

def parse_search_albums_and_songs(resp: dict, song_limit: int | None = None, album_limit: int | None = None, yt_innertube=None, yt_api=None, enrich_metadata: bool = False) -> dict:
    songs, albums = [], []
    tab = _get_selected_tab(resp)
    if not tab: return {"songs": songs, "albums": albums}
    sections = _dig(tab, ["content","sectionListRenderer","contents"], []) or []
    for sec in sections:
        shelf = sec.get("musicShelfRenderer")
        if not shelf: continue
        for it in shelf.get("contents", []) or []:
            mrlir = it.get("musicResponsiveListItemRenderer")
            if not mrlir: continue

            if _is_album_row(mrlir):
                album = _extract_album_item_from_search(mrlir)
                if album.get("album_id") or album.get("playlist_id"):
                    albums.append(album)
                continue

            if _is_atv_song_row(mrlir):
                links = _extract_menu_navs(mrlir)
                s = _extract_song_item(mrlir)
                if s.get("track_id"):
                    songs.append({
                        "title": s.get("title"),
                        "track_id": s.get("track_id"),
                        "artists": s.get("artists", []),
                        "thumbnails": s.get("thumbnails", []),
                        "type": "song",
                        "go_to": {"album_id": links["album_id"], "artist_id": links["artist_id"]},
                        "duration": s.get("duration"),
                    })

        if (album_limit is not None and len(albums) >= album_limit) and (song_limit is not None and len(songs) >= song_limit):
            break

    if enrich_metadata and yt_innertube and yt_api:
        _enrich_songs_with_metadata(yt_innertube, yt_api, songs)
    
    if song_limit is not None: songs = songs[:song_limit]
    if album_limit is not None: albums = albums[:album_limit]
    return {"songs": songs, "albums": albums}

# ---------- ARTIST CARD → ALBUMS ----------
def _extract_album_item(mrlir: dict) -> dict:
    title_runs = _runs(mrlir, 0)
    title = _dig(title_runs, [0,"text"]) or _runs_text(title_runs) or None
    album_browse_id = _dig(mrlir, ["navigationEndpoint","browseEndpoint","browseId"])
    playlist_id = _dig(mrlir, [
        "overlay","musicItemThumbnailOverlayRenderer","content","musicPlayButtonRenderer",
        "playNavigationEndpoint","watchPlaylistEndpoint","playlistId"
    ])
    artists = []
    for r in _runs(mrlir, 1):
        if _page_type_from(r) == "MUSIC_PAGE_TYPE_ARTIST":
            artists.append({"name": r.get("text",""), "artist_id": _dig(r,["navigationEndpoint","browseEndpoint","browseId"])})
    year = None
    for r in reversed(_runs(mrlir, 1)):
        t = (r or {}).get("text","").strip()
        if len(t) == 4 and t.isdigit(): year = t; break
    thumbs = _dig(mrlir, ["thumbnail","musicThumbnailRenderer","thumbnail","thumbnails"], []) or []
    links = _extract_menu_navs(mrlir)
    return {
        "title": title,
        "album_id": album_browse_id,
        "playlist_id": playlist_id,
        "artists": artists,
        "year": year,
        "thumbnails": thumbs,
        "type": "album",
        "go_to": {"artist_id": links["artist_id"]},
    }

def parse_artist_card_albums(resp: dict, limit: int | None = None) -> list[dict]:
    out = []
    tab = _get_selected_tab(resp)
    if not tab: return out
    sections = _dig(tab, ["content","sectionListRenderer","contents"], []) or []
    if not sections: return out
    card = None
    for sec in sections:
        if "musicCardShelfRenderer" in sec:
            card = sec["musicCardShelfRenderer"]
            break
    if not card: return out

    title_runs = _dig(card, ["title","runs"], []) or []
    nav = title_runs[0].get("navigationEndpoint", {}) if title_runs else {}
    if _dig(nav, [
        "browseEndpoint","browseEndpointContextSupportedConfigs",
        "browseEndpointContextMusicConfig","pageType"
    ]) != "MUSIC_PAGE_TYPE_ARTIST":
        return out

    for it in card.get("contents", []) or []:
        mrlir = it.get("musicResponsiveListItemRenderer"); 
        if not mrlir: continue
        if not _is_album_row(mrlir): continue
        album = _extract_album_item(mrlir)
        if not (album.get("album_id") or album.get("playlist_id")): continue
        out.append(album)
        if limit is not None and len(out) >= limit: break
    return out

# ---------- BÚSQUEDA GENERAL → ALBUMS + SONGS (filtra episodios/videos) ----------
def _extract_album_item_from_search(mrlir: dict) -> dict:
    # reusa la misma lógica de álbum
    return _extract_album_item(mrlir)

# ---------- TOP RESULT (musicCardShelfRenderer) ----------
def parse_search_top_result(resp: dict) -> dict | None:
    """
    Devuelve el top result si existe y es MUSIC_VIDEO_TYPE_ATV.
    Incluye título, artistas, duración y thumbnail.
    """
    try:
        tab = _get_selected_tab(resp)
        if not tab:
            return None

        sections = _dig(tab, ["content", "sectionListRenderer", "contents"], []) or []
        card = next((c.get("musicCardShelfRenderer") for c in sections if "musicCardShelfRenderer" in c), None)
        if not card:
            return None

        title_runs = _dig(card, ["title", "runs"], []) or []
        title_text = _dig(title_runs, [0, "text"])
        nav = _dig(title_runs, [0, "navigationEndpoint", "watchEndpoint"], {})
        video_id = nav.get("videoId")
        video_type = _dig(nav, [
            "watchEndpointMusicSupportedConfigs",
            "watchEndpointMusicConfig",
            "musicVideoType"
        ])

        # Solo si es ATV devolvemos algo
        if video_type != "MUSIC_VIDEO_TYPE_ATV":
            return None

        # --- artistas ---
        artists = []
        subtitle_runs = _dig(card, ["subtitle", "runs"], []) or []
        for run in subtitle_runs:
            bid = _dig(run, ["navigationEndpoint", "browseEndpoint", "browseId"])
            if bid and run.get("text"):
                artists.append({"name": run["text"], "artist_id": bid})

        # --- duración ---
        duration = None
        for run in subtitle_runs:
            txt = run.get("text", "")
            if ":" in txt:
                duration = txt
                break

        # --- thumbnail ---
        thumbs = _dig(card, [
            "thumbnail", "musicThumbnailRenderer", "thumbnail", "thumbnails"
        ], []) or []
        thumb_url = thumbs[-1]["url"] if thumbs else None

        return {
            "title": title_text,
            "track_id": video_id,
            "artists": artists,
            "duration": duration,
            "thumbnail_url": thumb_url,
        }

    except Exception:
        return None

# ---------- COMBINADO: TOP RESULT + SONGS ----------
def parse_search_first_song_or_top(resp: dict) -> tuple[str | None, dict | None]:
    """
    Busca primero el TopResult (musicCardShelfRenderer),
    si no hay o no es ATV, busca en el shelf 'Songs'.
    Devuelve (source, song)
    """
    top = parse_search_top_result(resp)
    if top:
        return "TopResult", top

    songs = parse_search_songs(resp)
    if songs:
        return "Songs", songs[0]

    return None, None

# ---------- CARD DE ARTISTA (lista de 1 si hay) ----------
def parse_search_artists(resp: dict) -> list[dict]:
    out = []
    info = parse_artist_card_info(resp)
    if info: out.append(info)
    return out