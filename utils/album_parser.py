import re
from urllib.parse import urlparse, parse_qs
from shared.clients import _ytmusic_client, _ytm
from .artist_parser import parse_albums as _artist_parse_albums, parse_singles_eps as _artist_parse_singles

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

def _parse_strapline_artists(header: dict) -> list[dict]:
    """
    Devuelve todos los artistas del straplineTextOne:
    [{ id: <browseId>, name: <texto> }, ...]
    Ignora separadores tipo '&', '•', ','.
    """
    runs = ((header.get("straplineTextOne") or {}).get("runs") or [])
    out = []
    for r in runs:
        name = (r.get("text") or "").strip()
        be = ((r.get("navigationEndpoint") or {}).get("browseEndpoint") or {})
        bid = be.get("browseId")
        if not bid or not name or name in {"&", "•", ","}:
            continue
        out.append({"id": bid, "name": name})
    return out

def _parse_strapline_thumbnail(header: dict) -> list[dict]:
    """
    Devuelve la lista de thumbnails del straplineThumbnail.
    """
    return (
        (header.get("straplineThumbnail") or {})
          .get("musicThumbnailRenderer", {})
          .get("thumbnail", {})
          .get("thumbnails", [])
        or []
    )

def parse_album_info(response: dict):
    """
    Extrae info general del álbum desde el browse() crudo.
    - PRIORIDAD de título/metadata: musicResponsiveHeaderRenderer
    - Fallback para thumbs/url/etc: microformat
    - AGREGA: audio_playlist_id (OLAK5…) y, si existe, recorta url -> OLAK5…
    """
    # ---------- Header (titulo/artist/songs/duration) ----------
    header = _find_album_header(response)

    title_hdr = None
    artist_name = None
    artist_id = None
    song_count = None
    duration_text = None
    year = None
    included_artists = []
    strapline_thumbs = []

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

        # More artists (straplineTextOne)
        included_artists = _parse_strapline_artists(header)

        # Compat: primer artista (si existe) igual que antes
        if included_artists:
            artist_name = included_artists[0].get("name")
            artist_id = included_artists[0].get("id")
        else:
            # fallback al primer run como lo hacías
            runs_one = ((header.get("straplineTextOne") or {}).get("runs") or [])
            if runs_one:
                r0 = runs_one[0] or {}
                artist_name = r0.get("text")
                artist_id = (
                    ((r0.get("navigationEndpoint") or {}).get("browseEndpoint") or {})
                    .get("browseId")
                )

        # "N songs • M minutes" (secondSubtitle)
        ss_runs = ((header.get("secondSubtitle") or {}).get("runs") or [])
        joined = " ".join((r or {}).get("text", "") for r in ss_runs)
        m_songs = re.search(r"(\d+)\s*(?:songs?|canciones?)", joined, re.IGNORECASE)
        if m_songs:
            try:
                song_count = int(m_songs.group(1))
            except Exception:
                song_count = None

        # Duración
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

    # thumbnails del strapline (si existen)
    strapline_thumbs = _parse_strapline_thumbnail(header)

    # ---------- Microformat (thumbs/url/description/site) ----------
    micro = (
        response.get("microformat", {})
        .get("microformatDataRenderer", {})
    )

    title_micro = micro.get("title")
    description = micro.get("description")
    url = micro.get("urlCanonical")
    thumbnails = micro.get("thumbnail", {}).get("thumbnails", [])

    # Derivar audio_playlist_id desde urlCanonical / applinks
    audio_playlist_id = None
    candidatos = [
        micro.get("urlCanonical"),
        micro.get("urlApplinksWeb"),
        micro.get("urlApplinksIos"),
        micro.get("urlApplinksAndroid"),
    ]
    for c in candidatos:
        if not c or not isinstance(c, str):
            continue
        if c.startswith("OLAK5"):
            audio_playlist_id = c
            break
        try:
            q = parse_qs(urlparse(c).query)
            cand = (q.get("list") or [None])[0]
            if cand and isinstance(cand, str) and cand.startswith("OLAK5"):
                audio_playlist_id = cand
                break
        except Exception:
            pass

    # Si tenemos OLAK5… y url era una URL, la recortamos a sólo el ID (lo pediste explícitamente)
    if audio_playlist_id:
        url = audio_playlist_id

    # PRIORIDAD de título al header; fallback al micro
    title = title_hdr or title_micro

    payload = {
        "title": title,
        "description": description,
        "url": url,  # queda "OLAK5…" si se pudo recortar
        "thumbnails": thumbnails,

        ## TODO: { debería tener esto teniendo included_artists? 
        "artist_name": artist_name, 
        "artist_id": artist_id, 
        ## TODO }

        "included_artists": included_artists,      # [{id,name}, ...]
        "strapline_thumbnail": strapline_thumbs,   # lista de thumbs del strapline

        "song_count": song_count,
        "duration_text": duration_text,
        "year": year,
    }

    if audio_playlist_id:
        payload["audio_playlist_id"] = audio_playlist_id

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

def _first_text(runlist: list) -> str | None:
    if not runlist:
        return None
    t = runlist[0].get("text")
    return t if isinstance(t, str) else None

def _duration_to_seconds(d: str | None) -> int | None:
    if not d or not isinstance(d, str):
        return None
    parts = d.strip().split(":")
    if not all(p.isdigit() for p in parts):
        return None
    nums = [int(p) for p in parts]
    if len(nums) == 2:  # mm:ss
        m, s = nums
        return m * 60 + s
    if len(nums) == 3:  # hh:mm:ss
        h, m, s = nums
        return h * 3600 + m * 60 + s
    return None

def _try_fix_collab_artists(artists: list[dict], album_artists: list[dict]) -> list[dict]:
    """
    Si el track viene con 1 artista, id=null y nombre concatenado,
    splitea el nombre en N artistas y matchea cada uno con included_artists
    del album. Los que matchean reciben su id, los que no quedan con id=null.
    """
    if (
        len(artists) != 1
        or artists[0].get("id") is not None
        or not artists[0].get("name")
    ):
        return artists

    name_concat = artists[0]["name"]
    parts = [p.strip() for p in name_concat.replace("&", ",").split(",") if p.strip()]
    if not parts:
        return artists

    album_map = {
        a["name"].strip().lower(): a["id"]
        for a in (album_artists or [])
        if a.get("name") and a.get("id")
    }

    return [
        {"id": album_map.get(name.lower()), "name": name}
        for name in parts
    ]

def _try_fix_collab_artists(artists: list[dict], album_artists: list[dict]) -> list[dict]:
    """
    Si el track viene con 1 artista, id=null y nombre concatenado,
    splitea el nombre en N artistas y matchea cada uno con included_artists
    del album. Los que matchean reciben su id, los que no quedan con id=null.
    """
    if (
        len(artists) != 1
        or artists[0].get("id") is not None
        or not artists[0].get("name")
    ):
        return artists

    name_concat = artists[0]["name"]
    parts = [p.strip() for p in name_concat.replace("&", ",").split(",") if p.strip()]
    if not parts:
        return artists

    album_map = {
        a["name"].strip().lower(): a["id"]
        for a in (album_artists or [])
        if a.get("name") and a.get("id")
    }

    return [
        {"id": album_map.get(name.lower()), "name": name}
        for name in parts
    ]

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

            # Duration seconds
            duration_seconds = _duration_to_seconds(duration)    

            # Index impreso
            index_print = None
            if "index" in renderer:
                runs = renderer["index"].get("runs", [])
                index_print = _first_text(runs)

            tracks.append({
                "title": title,
                "track_id": video_id,
                "artists": artists,
                "plays": plays,
                "duration": duration,
                "duration_seconds": duration_seconds,
                "index": index_print,
            })

    return tracks

def parse_tracks_from_audio_playlist(
    audio_playlist_id: str,
    album_artists: list[dict] | None = None,
) -> list[dict]:
    """
    Devuelve lista de tracks con el MISMO shape que parse_album_tracks(),
    usando ytmusicapi.get_playlist (ATV). Nunca OMV.

    album_artists: included_artists del album, usados para matchear ids
    en colaboraciones que YT devuelve sin parsear.
    """
    ytm_local = _ytmusic_client()  # evita estado raro del global

    try:
        pl = ytm_local.get_playlist(audio_playlist_id, limit=None) or {}
        src = pl.get("tracks") or []
    except Exception as e:
        print(f"[parse_tracks_from_audio_playlist][WARN] get_playlist failed: {e}")
        return []

    out: list[dict] = []
    for idx, t in enumerate(src, start=1):
        # título
        title = t.get("title")

        # videoId
        video_id = t.get("videoId")

        # artistas -> [{id,name}]
        artists = []
        for a in (t.get("artists") or []):
            if isinstance(a, dict):
                nm = a.get("name")
                bid = a.get("id")
                if nm or bid:
                    artists.append({"id": bid, "name": nm})

        # FIX: rellenar id de colabs unparsed usando album_artists
        artists = _try_fix_collab_artists(artists, album_artists or [])

        # duración: ytmusicapi usa 'duration' (a veces 'duration_seconds' también)
        duration = t.get("duration") or t.get("length")

        duration_seconds = t.get("duration_seconds") or _duration_to_seconds(duration)

        # índice impreso (string, como en parse_album_tracks)
        index_print = str(idx)

        out.append({
            "title": title,
            "track_id": video_id,
            "artists": artists,
            "duration": duration,
            "duration_seconds": duration_seconds,
            "index": index_print,
            "credits_browse_id": t.get("creditsBrowseId"),
        })

    return out

def parse_album_other_versions(album_response: dict) -> list[dict]:
    """
    Extrae el carrusel 'Other versions' (u 'Otras versiones') del browse del álbum.
    Devuelve: [{ title, browseId, params, type, artist_name, thumbnails }]
    """
    def _title_of(header: dict) -> str:
        runs = ((header or {}).get("musicCarouselShelfBasicHeaderRenderer", {})
            .get("title", {}).get("runs", [])) or []
        return (runs[0].get("text") if runs and isinstance(runs[0], dict) else "") or ""

    def _thumbs(node: dict) -> list:
        return (node.get("thumbnailRenderer", {})
            .get("musicThumbnailRenderer", {})
            .get("thumbnail", {})
            .get("thumbnails", [])) or []

    # twoColumn → secondaryContents → sectionListRenderer → contents[]
    contents = (
        album_response.get("contents", {})
        .get("twoColumnBrowseResultsRenderer", {})
        .get("secondaryContents", {})
        .get("sectionListRenderer", {})
        .get("contents", []) or []
    )

    out: list[dict] = []

    for sec in contents:
        shelf = sec.get("musicCarouselShelfRenderer")
        if not shelf:
            continue

        # ¿Este carrusel es "Other versions"?
        title_txt = _title_of(shelf.get("header", {})).strip().lower()
        if title_txt not in ("other versions", "otras versiones"):
            continue

        for it in shelf.get("contents", []) or []:
            row = it.get("musicTwoRowItemRenderer") or {}
            # título
            title_runs = (row.get("title", {}) or {}).get("runs", []) or []
            title = (title_runs[0].get("text") if title_runs else None)

            # destino (álbum alternativo)
            nav = (row.get("navigationEndpoint", {}) or {}).get("browseEndpoint", {}) or {}
            bid = nav.get("browseId")
            params = nav.get("params")

            # subtítulo → tipo (Album/EP/Single) y artista
            sub_runs = (row.get("subtitle", {}) or {}).get("runs", []) or []
            type_txt = sub_runs[0].get("text") if sub_runs else None
            # artista (si viene como run con endpoint)
            artist_name = None
            for r in sub_runs:
                be = (r.get("navigationEndpoint", {}) or {}).get("browseEndpoint", {}) or {}
                if be.get("browseId"):
                    artist_name = r.get("text")
                    break
            # fallback: si no vino run navegable, intenta leer texto plano
            if not artist_name and len(sub_runs) >= 3:
                artist_name = sub_runs[-1].get("text")

            out.append({
                "title": title,
                "id": bid,
                "params": params,
                "type": type_txt, # p.ej. "Album", "EP", "Single"
                "artist_name": artist_name,  # p.ej. "Justin Bieber"
                "thumbnails": _thumbs(row),
            })

    return out

def parse_album_releases_for_you(album_response: dict) -> list[dict]:
    """
    Extrae el carrusel 'Releases for you' del browse del álbum.
    Filtra los ítems donde el artista sea 'Various Artists'.
    Devuelve: [{ title, browseId, params, type, artist_name, thumbnails }]
    """
    def _title_of(header: dict) -> str:
        runs = ((header or {}).get("musicCarouselShelfBasicHeaderRenderer", {})
                .get("title", {}).get("runs", [])) or []
        return (runs[0].get("text") if runs and isinstance(runs[0], dict) else "") or ""

    def _thumbs(node: dict) -> list:
        return (node.get("thumbnailRenderer", {})
                    .get("musicThumbnailRenderer", {})
                    .get("thumbnail", {})
                    .get("thumbnails", [])) or []

    contents = (
        album_response.get("contents", {})
        .get("twoColumnBrowseResultsRenderer", {})
        .get("secondaryContents", {})
        .get("sectionListRenderer", {})
        .get("contents", []) or []
    )

    out: list[dict] = []
    for sec in contents:
        shelf = sec.get("musicCarouselShelfRenderer")
        if not shelf:
            continue

        title_txt = _title_of(shelf.get("header", {})).strip().lower()
        if title_txt not in ("releases for you", "lanzamientos para ti"):
            continue

        for it in shelf.get("contents", []) or []:
            row = it.get("musicTwoRowItemRenderer") or {}

            # título
            title_runs = (row.get("title", {}) or {}).get("runs", []) or []
            title = (title_runs[0].get("text") if title_runs else None)

            # destino (álbum / single / EP)
            nav = (row.get("navigationEndpoint", {}) or {}).get("browseEndpoint", {}) or {}
            bid = nav.get("browseId")
            params = nav.get("params")

            # subtítulo (tipo + artista)
            sub_runs = (row.get("subtitle", {}) or {}).get("runs", []) or []
            type_txt = sub_runs[0].get("text") if sub_runs else None

            # artista (preferir el run navegable; si no, último texto)
            artist_name = None
            for r in sub_runs:
                be = (r.get("navigationEndpoint", {}) or {}).get("browseEndpoint", {}) or {}
                if be.get("browseId"):
                    artist_name = r.get("text")
                    break
            if not artist_name and len(sub_runs) >= 3:
                artist_name = sub_runs[-1].get("text")

            # filtro: excluir 'Various Artists'
            if isinstance(artist_name, str) and artist_name.strip().lower() == "various artists":
                continue

            out.append({
                "title": title,
                "id": bid,
                "params": params,
                "type": type_txt,           # "Album" | "Single" | "EP"
                "artist_name": artist_name,  # p.ej. "Reggie Becton"
                "thumbnails": _thumbs(row),
            })

    return out

def build_more_from_artist(artist_id: str, exclude_album_id: str | None = None, limit: int = 10) -> list[dict]:
    """
    Devuelve una mezcla de Albums + Singles/EPs del artista dado, excluyendo el álbum actual.
    Shape de cada item: { id, title, type, year, thumbnails }
    - type: "Album" | "Single" | "EP"
    """
    if not artist_id:
        return []

    try:
        yt = _ytm()
        aresp = yt.browse(artist_id)

        # Navega a la misma ruta que ya usás para artista
        acontents = (
            aresp.get("contents", {})
                 .get("singleColumnBrowseResultsRenderer", {})
                 .get("tabs", [])[0]
                 .get("tabRenderer", {})
                 .get("content", {})
                 .get("sectionListRenderer", {})
                 .get("contents", [])
        ) or []

        out: list[dict] = []

        # Álbumes (sección 1): marcamos type="Album"
        if len(acontents) > 1:
            for it in (_artist_parse_albums(acontents[1]) or []):
                iid = it.get("id")
                if iid and iid != exclude_album_id:
                    row = dict(it)
                    row["type"] = "Album"
                    out.append(row)

        # Singles / EPs (sección 2): ya traen "type"
        if len(acontents) > 2:
            for it in (_artist_parse_singles(acontents[2]) or []):
                iid = it.get("id")
                if iid and iid != exclude_album_id:
                    out.append(it)

        # Dedupe por id y recorte
        seen: set[str] = set()
        dedup: list[dict] = []
        for it in out:
            iid = it.get("id")
            if not iid or iid in seen:
                continue
            seen.add(iid)
            dedup.append(it)

        return dedup[:max(0, int(limit))]
    except Exception as e:
        print("[album_parser][build_more_from_artist][WARN]", e)
        return []