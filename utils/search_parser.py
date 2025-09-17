# utils/search_parser.py
import re

# -------- helpers básicos --------
def _dig(cur, path, default=None):
    """Acceso seguro a diccionarios/listas con rutas tipo ['a', 0, 'b']."""
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

def _runs_text(runs):
    return "".join((r or {}).get("text", "") for r in (runs or []))

def _get_selected_tab(resp: dict):
    tabs = _dig(resp, ["contents", "tabbedSearchResultsRenderer", "tabs"], [])
    for t in tabs:
        tr = t.get("tabRenderer") or t.get("expandableTabRenderer")
        if tr and tr.get("selected"):
            return tr
    return None

def _is_songs_shelf(shelf: dict) -> bool:
    title_runs = _dig(shelf, ["title", "runs"], [])
    title_text = _runs_text(title_runs).strip().lower()
    return title_text in ("songs", "canciones")

def _runs(mrlir, col_idx):
    return _dig(mrlir, ["flexColumns", col_idx, "musicResponsiveListItemFlexColumnRenderer", "text", "runs"], []) or []

def _parse_duration(info_runs, accessibility_label):
    # 1) buscar "mm:ss" o "h:mm:ss" en los runs
    for r in reversed(info_runs or []):
        txt = (r or {}).get("text", "")
        parts = txt.split(":")
        if len(parts) in (2, 3) and all(p.isdigit() for p in parts):
            return txt
    # 2) fallback: "3 minutes, 32 seconds" -> mm:ss / h:mm:ss
    if accessibility_label:
        m = re.search(r"(?:(\d+)\s+hours?,\s*)?(?:(\d+)\s+minutes?,\s*)?(\d+)\s+seconds?", accessibility_label)
        if m:
            h = int(m.group(1) or 0)
            mnt = int(m.group(2) or 0)
            sec = int(m.group(3) or 0)
            total = h * 3600 + mnt * 60 + sec
            if total >= 3600:
                hh = total // 3600
                mm = (total % 3600) // 60
                ss = total % 60
                return f"{hh}:{mm:02d}:{ss:02d}"
            else:
                mm = total // 60
                ss = total % 60
                return f"{mm}:{ss:02d}"
    return None

# -------- canciones (Songs/Canciones) --------
def _extract_song_item(mrlir: dict) -> dict:
    title_runs = _runs(mrlir, 0)           # columna Título
    info_runs  = _runs(mrlir, 1)           # columna Artista • Álbum • Duración

    # título (si hay múltiples runs, se unen)
    title = _dig(title_runs, [0, "text"]) or _runs_text(title_runs) or None

    # artistas (pueden ser varios)
    artists = []
    for r in info_runs:
        page_type = _dig(r, [
            "navigationEndpoint","browseEndpoint",
            "browseEndpointContextSupportedConfigs","browseEndpointContextMusicConfig","pageType"
        ])
        if page_type == "MUSIC_PAGE_TYPE_ARTIST":
            artists.append({
                "name": r.get("text", ""),
                "browseId": _dig(r, ["navigationEndpoint", "browseEndpoint", "browseId"])
            })

    # álbum (si existe)
    album = None
    for r in info_runs:
        page_type = _dig(r, [
            "navigationEndpoint","browseEndpoint",
            "browseEndpointContextSupportedConfigs","browseEndpointContextMusicConfig","pageType"
        ])
        if page_type == "MUSIC_PAGE_TYPE_ALBUM":
            album = {
                "name": r.get("text", ""),
                "browseId": _dig(r, ["navigationEndpoint", "browseEndpoint", "browseId"])
            }
            break

    accessibility_label = _dig(mrlir, ["accessibility","accessibilityData","label"])
    duration = _parse_duration(info_runs, accessibility_label)

    # videoId (pista) y tipo (ATV)
    video_id = (
        _dig(mrlir, ["playlistItemData", "videoId"]) or
        _dig(title_runs, [0, "navigationEndpoint", "watchEndpoint", "videoId"]) or
        _dig(mrlir, [
            "overlay","musicItemThumbnailOverlayRenderer","content","musicPlayButtonRenderer",
            "playNavigationEndpoint","watchEndpoint","videoId"
        ])
    )
    music_video_type = (
        _dig(title_runs, [
            0,"navigationEndpoint","watchEndpoint",
            "watchEndpointMusicSupportedConfigs","watchEndpointMusicConfig","musicVideoType"
        ]) or
        _dig(mrlir, [
            "overlay","musicItemThumbnailOverlayRenderer","content","musicPlayButtonRenderer",
            "playNavigationEndpoint","watchEndpoint","watchEndpointMusicSupportedConfigs",
            "watchEndpointMusicConfig","musicVideoType"
        ])
    )

    thumbs = _dig(mrlir, ["thumbnail","musicThumbnailRenderer","thumbnail","thumbnails"], []) or []

    return {
        "title": title,
        "artists": artists,              # [{name, browseId}, ...]
        "album": album,                  # {name, browseId} | None
        "duration": duration,            # "3:32" / "h:mm:ss"
        "videoId": video_id,
        "musicVideoType": music_video_type,  # debería ser "MUSIC_VIDEO_TYPE_ATV"
        "thumbnails": thumbs,
        # para debug/uso avanzado:
        "title_runs": title_runs,
        "info_runs": info_runs,
    }

def parse_search_songs(resp: dict, strict_atv: bool = True) -> list[dict]:
    """
    Devuelve todos los items del shelf 'Songs/Canciones' como objetos completos.
    Si strict_atv=True, filtra a solo 'MUSIC_VIDEO_TYPE_ATV'.
    """
    out = []
    tab = _get_selected_tab(resp)
    if not tab:
        return out

    sections = _dig(tab, ["content", "sectionListRenderer", "contents"], []) or []
    for sec in sections:
        shelf = sec.get("musicShelfRenderer")
        if not shelf or not _is_songs_shelf(shelf):
            continue

        for it in shelf.get("contents", []):
            mrlir = it.get("musicResponsiveListItemRenderer")
            if not mrlir:
                continue
            item = _extract_song_item(mrlir)
            if not item.get("videoId"):
                continue
            if strict_atv and item.get("musicVideoType") != "MUSIC_VIDEO_TYPE_ATV":
                continue
            out.append(item)

        break  # solo el primer shelf "Songs/Canciones"
    return out

# -------- artistas (card de artista en resultados) --------
def parse_search_artists(resp: dict) -> list[dict]:
    """
    Extrae tarjetas de artista (musicCardShelfRenderer) con name, artistId, subtitle, thumbnails.
    """
    artists = []
    tab = _get_selected_tab(resp)
    if not tab:
        return artists

    sections = _dig(tab, ["content", "sectionListRenderer", "contents"], []) or []
    for sec in sections:
        card = sec.get("musicCardShelfRenderer")
        if not card:
            continue

        title_runs = _dig(card, ["title", "runs"], []) or []
        if not title_runs:
            continue

        nav = title_runs[0].get("navigationEndpoint", {})
        browse = nav.get("browseEndpoint")
        if not browse:
            continue

        page_type = _dig(nav, [
            "browseEndpoint","browseEndpointContextSupportedConfigs",
            "browseEndpointContextMusicConfig","pageType"
        ])
        if page_type != "MUSIC_PAGE_TYPE_ARTIST":
            continue

        name = title_runs[0].get("text", "")
        artist_id = browse.get("browseId")
        subtitle = _runs_text(_dig(card, ["subtitle","runs"], []))
        thumbs = _dig(card, ["thumbnail","musicThumbnailRenderer","thumbnail","thumbnails"], []) or []

        artists.append({
            "name": name,
            "artistId": artist_id,
            "subtitle": subtitle,
            "thumbnails": thumbs,
        })

    return artists