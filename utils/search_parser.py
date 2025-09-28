# utils/search_parser.py
import re

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
    # 1) texto “episode/episodio”
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
    out = {"albumId": None, "artistId": None, "albumItem": None, "artistItem": None}
    def _txt(nir): return (_dig(nir, ["text","runs",0,"text"]) or "").strip().lower()
    for it in items:
        nir = it.get("menuNavigationItemRenderer"); 
        if not nir: continue
        txt = _txt(nir)
        be = _dig(nir, ["navigationEndpoint","browseEndpoint"], {}) or {}
        bid = be.get("browseId")
        pgt = _page_type_from(nir)
        if bid and pgt == "MUSIC_PAGE_TYPE_ALBUM" and ( "go to album" in txt or "ir al álbum" in txt or "ir al album" in txt or txt == "album" ):
            out["albumId"], out["albumItem"] = bid, nir
        if bid and pgt == "MUSIC_PAGE_TYPE_ARTIST" and ( "go to artist" in txt or "ir al artista" in txt or txt in ("artist","artista") ):
            out["artistId"], out["artistItem"] = bid, nir
    return out

# ---------- extracción de SONG ----------
def _extract_song_item(mrlir: dict) -> dict:
    title_runs = _runs(mrlir, 0)
    info_runs  = _runs(mrlir, 1)

    title = _dig(title_runs, [0,"text"]) or _runs_text(title_runs) or None

    artists = []
    for r in info_runs:
        if _page_type_from(r) == "MUSIC_PAGE_TYPE_ARTIST":
            artists.append({"name": r.get("text",""), "browseId": _dig(r,["navigationEndpoint","browseEndpoint","browseId"])})

    album = None
    for r in info_runs:
        if _page_type_from(r) == "MUSIC_PAGE_TYPE_ALBUM":
            album = {"name": r.get("text",""), "browseId": _dig(r,["navigationEndpoint","browseEndpoint","browseId"])}
            break

    duration = _parse_duration(info_runs, _dig(mrlir, ["accessibility","accessibilityData","label"]))
    thumbs = _dig(mrlir, ["thumbnail","musicThumbnailRenderer","thumbnail","thumbnails"], []) or []

    return {
        "title": title,
        "artists": artists,
        "album": album,
        "duration": duration,                    # OJO: la card de artista no la expondrá
        "videoId": _video_id(mrlir),
        "musicVideoType": _mvtype(mrlir),
        "thumbnails": thumbs,
        # debug opcional
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
            if not item.get("videoId"): continue
            if strict_atv and item.get("musicVideoType") != "MUSIC_VIDEO_TYPE_ATV": continue
            out.append(item)
        break
    return out

# ---------- ARTIST CARD → ARTIST INFO ----------
def parse_artist_card_info(resp: dict) -> dict | None:
    tab = _get_selected_tab(resp)
    if not tab: return None
    sections = _dig(tab, ["content","sectionListRenderer","contents"], []) or []
    if not sections: return None
    card = sections[0].get("musicCardShelfRenderer")
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
        "artistId": artist_id,
        "subtitle": subtitle,
        "subtitleRuns": subtitle_runs,
        "subtitleTexts": subtitle_texts,
        "thumbnails": thumbs,
        "type": "artist",
    }

# ---------- ARTIST CARD → SONGS (sin duración) ----------
def parse_artist_card_songs(resp: dict, strict_atv: bool = True, limit: int | None = None) -> list[dict]:
    out = []
    tab = _get_selected_tab(resp)
    if not tab: return out
    sections = _dig(tab, ["content","sectionListRenderer","contents"], []) or []
    if not sections: return out
    card = sections[0].get("musicCardShelfRenderer")
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
        if not s.get("videoId"): continue
        if strict_atv and s.get("musicVideoType") != "MUSIC_VIDEO_TYPE_ATV": continue

        out.append({
            "title": s.get("title"),
            "videoId": s.get("videoId"),
            "artists": s.get("artists", []),
            "thumbnails": s.get("thumbnails", []),
            "musicVideoType": s.get("musicVideoType"),
            # sin duration en artist card
            "goTo": {"albumId": links["albumId"], "artistId": links["artistId"]},
        })
        if limit is not None and len(out) >= limit: break
    return out

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
            artists.append({"name": r.get("text",""), "browseId": _dig(r,["navigationEndpoint","browseEndpoint","browseId"])})
    year = None
    for r in reversed(_runs(mrlir, 1)):
        t = (r or {}).get("text","").strip()
        if len(t) == 4 and t.isdigit(): year = t; break
    thumbs = _dig(mrlir, ["thumbnail","musicThumbnailRenderer","thumbnail","thumbnails"], []) or []
    links = _extract_menu_navs(mrlir)
    return {
        "title": title,
        "albumId": album_browse_id,
        "playlistId": playlist_id,
        "artists": artists,
        "year": year,
        "thumbnails": thumbs,
        "type": "album",
        "goTo": {"artistId": links["artistId"]},
    }

def parse_artist_card_albums(resp: dict, limit: int | None = None) -> list[dict]:
    out = []
    tab = _get_selected_tab(resp)
    if not tab: return out
    sections = _dig(tab, ["content","sectionListRenderer","contents"], []) or []
    if not sections: return out
    card = sections[0].get("musicCardShelfRenderer")
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
        if not (album.get("albumId") or album.get("playlistId")): continue
        out.append(album)
        if limit is not None and len(out) >= limit: break
    return out

# ---------- BÚSQUEDA GENERAL → ALBUMS + SONGS (filtra episodios/videos) ----------
def _extract_album_item_from_search(mrlir: dict) -> dict:
    # reusa la misma lógica de álbum
    return _extract_album_item(mrlir)

def parse_search_albums_and_songs(resp: dict, song_limit: int | None = None, album_limit: int | None = None) -> dict:
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
                if album.get("albumId") or album.get("playlistId"):
                    albums.append(album)
                continue

            if _is_atv_song_row(mrlir):
                links = _extract_menu_navs(mrlir)
                s = _extract_song_item(mrlir)
                if s.get("videoId"):
                    songs.append({
                        "title": s.get("title"),
                        "videoId": s.get("videoId"),
                        "artists": s.get("artists", []),
                        "thumbnails": s.get("thumbnails", []),
                        "musicVideoType": s.get("musicVideoType"),
                        "type": "song",
                        "goTo": {"albumId": links["albumId"], "artistId": links["artistId"]},
                        # si querés exponer duración acá, ya viene en s["duration"]
                        "duration": s.get("duration"),
                    })

        if (album_limit is not None and len(albums) >= album_limit) and (song_limit is not None and len(songs) >= song_limit):
            break

    if song_limit is not None: songs = songs[:song_limit]
    if album_limit is not None: albums = albums[:album_limit]
    return {"songs": songs, "albums": albums}

# ---------- CARD DE ARTISTA (lista de 1 si hay) ----------
def parse_search_artists(resp: dict) -> list[dict]:
    out = []
    info = parse_artist_card_info(resp)
    if info: out.append(info)
    return out