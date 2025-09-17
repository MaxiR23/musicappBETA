import re

def _find_album_header(response: dict):
    """
    Busca el nodo musicResponsiveHeaderRenderer del álbum
    en los layouts más comunes (twoColumn / singleColumn).
    """
    contents = response.get("contents", {}) or {}

    # twoColumnBrowseResultsRenderer
    tc = contents.get("twoColumnBrowseResultsRenderer", {}) or {}
    tabs = tc.get("tabs") or []
    for t in tabs:
        tr = t.get("tabRenderer") or t.get("expandableTabRenderer") or {}
        slr = (tr.get("content") or {}).get("sectionListRenderer") or {}
        for c in slr.get("contents", []) or []:
            h = c.get("musicResponsiveHeaderRenderer")
            if h:
                return h

    # singleColumnBrowseResultsRenderer (fallback)
    sc = contents.get("singleColumnBrowseResultsRenderer", {}) or {}
    tabs = sc.get("tabs") or []
    for t in tabs:
        tr = t.get("tabRenderer") or t.get("expandableTabRenderer") or {}
        slr = (tr.get("content") or {}).get("sectionListRenderer") or {}
        for c in slr.get("contents", []) or []:
            h = c.get("musicResponsiveHeaderRenderer")
            if h:
                return h

    return None


def parse_album_info(response: dict):
    """
    Extrae info general del álbum.
    - PRIORIDAD de título/metadata: musicResponsiveHeaderRenderer (como pediste)
    - Fallback para thumbs/url/etc: microformat (se mantiene)
    """
    # ---------- Header (titulo/artist/songs/duration) ----------
    header = _find_album_header(response)

    title_hdr = None
    artist_name = None
    artist_id = None
    song_count = None
    duration_text = None
    year = None

    if header:
        # Título
        title_hdr = (
            ((header.get("title") or {}).get("runs") or [{}])[0].get("text")
        )

        # Artista (straplineTextOne)
        runs_one = ((header.get("straplineTextOne") or {}).get("runs") or [])
        if runs_one:
            r0 = runs_one[0] or {}
            artist_name = r0.get("text")
            artist_id = (
                ((r0.get("navigationEndpoint") or {}).get("browseEndpoint") or {})
                .get("browseId")
            )

        # "10 songs • 43 minutes" (secondSubtitle)
        ss_runs = ((header.get("secondSubtitle") or {}).get("runs") or [])
        # Juntar en texto para detectar 'songs/canciones'
        joined = " ".join((r or {}).get("text", "") for r in ss_runs)
        m_songs = re.search(r"(\d+)\s*(?:songs?|canciones?)", joined, re.IGNORECASE)
        if m_songs:
            try:
                song_count = int(m_songs.group(1))
            except Exception:
                song_count = None

        # Duración: tomar el primer run que mencione minutes/minutos/hours/horas
        for r in ss_runs:
            low = (r or {}).get("text", "").lower()
            if any(k in low for k in ("minute", "minuto", "minutes", "minutos", "hour", "hora", "hours", "horas")):
                duration_text = (r or {}).get("text")
                break

        # Año desde subtitle "Album • 2024" (opcional)
        sub_runs = ((header.get("subtitle") or {}).get("runs") or [])
        if sub_runs:
            last_txt = (sub_runs[-1] or {}).get("text", "")
            if isinstance(last_txt, str) and last_txt.isdigit() and len(last_txt) == 4:
                try:
                    year = int(last_txt)
                except Exception:
                    year = None

    # ---------- Microformat (thumbs/url/description/site) ----------
    micro = (
        response.get("microformat", {})
        .get("microformatDataRenderer", {})
    )

    title_micro = micro.get("title")
    description = micro.get("description")
    url = micro.get("urlCanonical")
    thumbnails = micro.get("thumbnail", {}).get("thumbnails", [])
    site_name = micro.get("siteName")

    # PRIORIDAD de título al header; fallback al micro
    title = title_hdr or title_micro

    payload = {
        "title": title,
        "description": description,
        "url": url,
        "thumbnails": thumbnails,
        "siteName": site_name,
        "links": {
            "applinksWeb": micro.get("urlApplinksWeb"),
            "applinksIos": micro.get("urlApplinksIos"),
            "applinksAndroid": micro.get("urlApplinksAndroid"),
        },
        # Nuevos campos pedidos (no rompen shape existente)
        "artistName": artist_name,
        "artistId": artist_id,
        "songCount": song_count,
        "durationText": duration_text,
        "year": year,
    }

    return payload


def parse_album_thumbnails_from_background(node: dict):
    """
    Extrae TODOS los thumbnails de un track/album desde 'background.musicThumbnailRenderer.thumbnail.thumbnails'.
    Ejemplo: track['overlay']['musicItemThumbnailOverlayRenderer']['background']
    """
    background = (
        node.get("musicThumbnailRenderer", {})
        .get("thumbnail", {})
        .get("thumbnails", [])
    )
    return background or []


def _extract_artist_name_from_accessibility(renderer: dict):
    """
    Intenta leer el nombre del artista desde el label de accesibilidad del play/pause.
    """
    overlay = renderer.get("overlay", {}).get("musicItemThumbnailOverlayRenderer", {})
    mpr = overlay.get("content", {}).get("musicPlayButtonRenderer", {})

    acc = (
        mpr.get("accessibilityPlayData", {}) or
        mpr.get("accessibilityPauseData", {})
    )
    label = acc.get("accessibilityData", {}).get("label")
    if not label or not isinstance(label, str):
        return None

    for pref in ("Play ", "Pause ", "Reproducir ", "Pausar "):
        if label.startswith(pref):
            label = label[len(pref):]
            break

    separators = [" - ", " — ", " by ", " de ", " • "]
    for sep in separators:
        if sep in label:
            parts = label.split(sep)
            if len(parts) >= 2:
                return parts[-1].strip() or None

    return None


def _find_any_browse_id(renderer: dict):
    """
    Busca un browseId de artista/canal en varios lugares comunes.
    """
    # 1) flexColumns[1] runs
    flex = renderer.get("flexColumns", [])
    if len(flex) > 1:
        runs = (
            flex[1]
            .get("musicResponsiveListItemFlexColumnRenderer", {})
            .get("text", {})
            .get("runs", [])
        )
        for run in runs:
            bid = (
                run.get("navigationEndpoint", {})
                .get("browseEndpoint", {})
                .get("browseId")
            )
            if bid:
                return bid

    # 2) menuRenderer items
    items = renderer.get("menu", {}).get("menuRenderer", {}).get("items", []) or []
    for it in items:
        mni = it.get("menuNavigationItemRenderer", {})
        bid = (
            mni.get("navigationEndpoint", {})
            .get("browseEndpoint", {})
            .get("browseId")
        )
        if bid:
            return bid

    # 3) subtitle runs
    sub_runs = renderer.get("subtitle", {}).get("runs", []) or []
    for run in sub_runs:
        bid = (
            run.get("navigationEndpoint", {})
            .get("browseEndpoint", {})
            .get("browseId")
        )
        if bid:
            return bid

    return None


def _detect_music_video_type(renderer: dict):
    """
    Devuelve 'MUSIC_VIDEO_TYPE_ATV' (song), 'MUSIC_VIDEO_TYPE_OMV' (video) o None.
    Lee primero el watch del botón Play, luego el del navigationEndpoint.
    """
    # overlay -> playNavigationEndpoint.watchEndpoint
    overlay = renderer.get("overlay", {}).get("musicItemThumbnailOverlayRenderer", {})
    mpr = overlay.get("content", {}).get("musicPlayButtonRenderer", {}) or {}
    watch = (
        mpr.get("playNavigationEndpoint", {}) or {}
    ).get("watchEndpoint", {}) or {}
    if not watch.get("videoId"):
        watch = renderer.get("navigationEndpoint", {}).get("watchEndpoint", {}) or {}

    cfg = (
        watch.get("watchEndpointMusicSupportedConfigs", {})
        .get("watchEndpointMusicConfig", {})
    )
    return cfg.get("musicVideoType")


def _first_text(runlist: list) -> str | None:
    if not runlist:
        return None
    t = runlist[0].get("text")
    return t if isinstance(t, str) else None


def parse_album_tracks(album_response: dict):
    """
    Devuelve las filas del álbum SIN cambiar el shape que ya usabas.
    Agrega un campo auxiliar 'musicVideoType' para que el caller decida (OMV→resolver).
    """
    contents = (
        album_response.get("contents", {})
        .get("twoColumnBrowseResultsRenderer", {})
        .get("secondaryContents", {})
        .get("sectionListRenderer", {})
        .get("contents", [])
    )

    tracks = []
    if not contents:
        return tracks

    for sec in contents:
        shelf = sec.get("musicShelfRenderer")
        if not shelf:
            continue

        for item in shelf.get("contents", []):
            renderer = item.get("musicResponsiveListItemRenderer")
            if not renderer:
                continue

            # Título
            title_runs = (
                renderer.get("flexColumns", [])[0]
                .get("musicResponsiveListItemFlexColumnRenderer", {})
                .get("text", {})
                .get("runs", [])
            )
            title = _first_text(title_runs)

            # Video ID (fila)
            video_id = (
                renderer.get("playlistItemData", {}).get("videoId")
                or renderer.get("navigationEndpoint", {}).get("watchEndpoint", {}).get("videoId")
            )

            # Artistas
            artists = []
            flex = renderer.get("flexColumns", [])
            if len(flex) > 1:
                runs = (
                    flex[1]
                    .get("musicResponsiveListItemFlexColumnRenderer", {})
                    .get("text", {})
                    .get("runs", [])
                )
                for run in runs:
                    if "navigationEndpoint" in run:
                        browse = run["navigationEndpoint"].get("browseEndpoint", {})
                        if browse.get("browseId"):
                            artists.append({
                                "id": browse["browseId"],
                                "name": run.get("text")
                            })

            if not artists:
                fallback_name = _extract_artist_name_from_accessibility(renderer)
                fallback_id = _find_any_browse_id(renderer)
                if fallback_name or fallback_id:
                    artists = [{"name": fallback_name, "id": fallback_id}]

            # Plays
            plays = None
            if len(renderer.get("flexColumns", [])) > 2:
                plays_runs = (
                    renderer["flexColumns"][2]
                    .get("musicResponsiveListItemFlexColumnRenderer", {})
                    .get("text", {}).get("runs", [])
                )
                plays = _first_text(plays_runs)

            # Duración
            duration = None
            fixed_cols = renderer.get("fixedColumns", [])
            if fixed_cols:
                runs = (
                    fixed_cols[0]
                    .get("musicResponsiveListItemFixedColumnRenderer", {})
                    .get("text", {})
                    .get("runs", [])
                )
                duration = _first_text(runs)

            # Index impreso
            index_print = None
            if "index" in renderer:
                runs = renderer["index"].get("runs", [])
                index_print = _first_text(runs)

            # Tipo (ATV/OMV)
            mvt = _detect_music_video_type(renderer)

            tracks.append({
                "title": title,
                "videoId": video_id,
                "artists": artists,
                "plays": plays,
                "duration": duration,
                "index": index_print,
                "musicVideoType": mvt,   # ← auxiliar para el caller (resolver OMV→ATV)
            })

    return tracks