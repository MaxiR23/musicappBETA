def parse_top_songs(section):
    songs = []
    shelf = section.get("musicShelfRenderer", {})
    for item in shelf.get("contents", []):
        r = item.get("musicResponsiveListItemRenderer")
        if not r:
            continue

        # videoId
        video_id = (
            r.get("overlay", {})
             .get("musicItemThumbnailOverlayRenderer", {})
             .get("content", {})
             .get("musicPlayButtonRenderer", {})
             .get("playNavigationEndpoint", {})
             .get("watchEndpoint", {})
             .get("videoId")
        )

        # título
        title_runs = (
            r.get("flexColumns", [])[0]
             .get("musicResponsiveListItemFlexColumnRenderer", {})
             .get("text", {})
             .get("runs", [])
        )
        title = title_runs[0]["text"] if title_runs else None

        # ARTISTAS (varios)
        artist_runs = (
            r.get("flexColumns", [])[1]
             .get("musicResponsiveListItemFlexColumnRenderer", {})
             .get("text", {})
             .get("runs", [])
        )
        artists = []
        for run in artist_runs:
            name = (run.get("text") or "").strip()
            browse = run.get("navigationEndpoint", {}).get("browseEndpoint", {})
            bid = browse.get("browseId")
            # ignorar separadores "•", "&", comas sueltas, etc., y quedarse con runs que tengan browseId
            if not bid or not name or name in {"•", "&", ","}:
                continue
            artists.append({"id": bid, "name": name})

        artist_name_joined = ", ".join(a["name"] for a in artists) if artists else None
        primary_artist_id = artists[0]["id"] if artists else None

        # Álbum (si está presente)
        album_id = None
        try:
            album_runs = (
                r.get("flexColumns", [])[3]
                 .get("musicResponsiveListItemFlexColumnRenderer", {})
                 .get("text", {})
                 .get("runs", [])
            )
            if album_runs:
                album_id = (
                    album_runs[0]
                    .get("navigationEndpoint", {})
                    .get("browseEndpoint", {})
                    .get("browseId")
                )
        except Exception:
            pass

        # Thumbnails
        thumbs = (
            r.get("thumbnail", {})
             .get("musicThumbnailRenderer", {})
             .get("thumbnail", {})
             .get("thumbnails", [])
        )

        songs.append({
            "id": video_id,
            "title": title,
            "thumbnail": thumbs[-1]["url"] if thumbs else None,
            "albumId": album_id,

            # Compat: se mantienen estos dos
            "artistId": primary_artist_id,
            "artistName": artist_name_joined,

            # Nuevo: lista completa de artistas
            "artists": artists,

            "duration": None,
            "durationSeconds": None,
        })
    return songs

def parse_albums(section):
    albums = []
    for item in section.get("musicCarouselShelfRenderer", {}).get("contents", []):
        r = item.get("musicTwoRowItemRenderer")
        if not r:
            continue

        # ID del álbum
        browse = (
            r.get("title", {})
            .get("runs", [{}])[0]
            .get("navigationEndpoint", {})
            .get("browseEndpoint", {})
        )
        album_id = browse.get("browseId")

        # Título
        title = r.get("title", {}).get("runs", [{}])[0].get("text")

        # Año (del subtitle)
        subtitle_runs = r.get("subtitle", {}).get("runs", [])
        year = None
        if subtitle_runs:
            year = subtitle_runs[0].get("text")

        # Thumbnails
        thumbs = (
            r.get("thumbnailRenderer", {})
            .get("musicThumbnailRenderer", {})
            .get("thumbnail", {})
            .get("thumbnails", [])
        )

        albums.append({
            "id": album_id,
            "title": title,
            "year": year,
            "thumbnails": thumbs
        })

    return albums

def parse_singles_eps(section):
    singles = []
    for item in section.get("musicCarouselShelfRenderer", {}).get("contents", []):
        r = item.get("musicTwoRowItemRenderer")
        if not r:
            continue

        # ID
        browse = (
            r.get("title", {})
            .get("runs", [{}])[0]
            .get("navigationEndpoint", {})
            .get("browseEndpoint", {})
        )
        single_id = browse.get("browseId")

        # Título
        title = r.get("title", {}).get("runs", [{}])[0].get("text")

        # Subtitle → [ "Single", " • ", "2025" ]
        subtitle_runs = r.get("subtitle", {}).get("runs", [])
        release_type = None
        year = None
        if subtitle_runs:
            release_type = subtitle_runs[0].get("text")
            if len(subtitle_runs) > 2:
                year = subtitle_runs[2].get("text")

        # Thumbnails
        thumbs = (
            r.get("thumbnailRenderer", {})
            .get("musicThumbnailRenderer", {})
            .get("thumbnail", {})
            .get("thumbnails", [])
        )

        singles.append({
            "id": single_id,
            "title": title,
            "type": release_type,  # "Single" o "EP"
            "year": year,
            "thumbnails": thumbs
        })

    return singles

def parse_featured_on(section):
    featured = []
    for item in section.get("musicCarouselShelfRenderer", {}).get("contents", []):
        r = item.get("musicTwoRowItemRenderer")
        if not r:
            continue

        # ID de playlist/album (browseId)
        browse = (
            r.get("title", {})
            .get("runs", [{}])[0]
            .get("navigationEndpoint", {})
            .get("browseEndpoint", {})
        )
        playlist_id = browse.get("browseId")

        # Título de la playlist
        title = r.get("title", {}).get("runs", [{}])[0].get("text")

        # Subtitle → normalmente "Playlist • YouTube Music"
        subtitle_runs = r.get("subtitle", {}).get("runs", [])
        subtitle = "".join(run.get("text", "") for run in subtitle_runs)

        # Thumbnails
        thumbs = (
            r.get("thumbnailRenderer", {})
            .get("musicThumbnailRenderer", {})
            .get("thumbnail", {})
            .get("thumbnails", [])
        )

        featured.append({
            "id": playlist_id,
            "title": title,
            "subtitle": subtitle,
            "thumbnails": thumbs
        })

    return featured

def section_header_text(sec: dict) -> str:
    """Devuelve el título del carrusel en minúsculas (si existe)."""
    return (
        sec.get("musicCarouselShelfRenderer", {})
          .get("header", {})
          .get("musicCarouselShelfBasicHeaderRenderer", {})
          .get("title", {})
          .get("runs", [{}])[0]
          .get("text", "") or ""
    ).strip().lower()

def is_related_artists_section(sec: dict) -> bool:
    """True si el header indica 'Artistas relacionados'."""
    h = section_header_text(sec)
    return any(k in h for k in (
        "fans might also like",   # EN
        "related artists",        # EN
        "artistas relacionados",  # ES
    ))

def pick_related_artists_section(contents: list[dict]) -> dict | None:
    """
    Busca el section correcto para 'Artistas relacionados'.
    1) Chequea índices (7, 9) por header.
    2) Si no, escanea todos por header.
    3) Fallback: devuelve el primero existente entre 7/9 que tenga carousel.
    """
    # 1) 7/9 por header
    for i in (7, 9):
        if i < len(contents) and is_related_artists_section(contents[i]):
            return contents[i]

    # 2) escaneo global por header (por si cambia de posición)
    for sec in contents:
        if is_related_artists_section(sec):
            return sec

    # 3) fallback: primer 7/9 con carrusel válido
    for i in (7, 9):
        if i < len(contents):
            car = contents[i].get("musicCarouselShelfRenderer", {})
            if car.get("contents"):
                return contents[i]

    return None

def parse_related_artists(section: dict):
    """
    Devuelve artistas relacionados.
    """
    related = []
    carousel = section.get("musicCarouselShelfRenderer", {})
    items = carousel.get("contents", [])

    for item in items:
        r = item.get("musicTwoRowItemRenderer")
        if not r:
            continue

        # Artist ID
        browse = (
            r.get("title", {})
            .get("runs", [{}])[0]
            .get("navigationEndpoint", {})
            .get("browseEndpoint", {})
        )
        artist_id = browse.get("browseId")

        # Nombre
        name = (
            r.get("title", {})
            .get("runs", [{}])[0]
            .get("text")
        )

        # Subtitle → "X monthly audience"
        subtitle_runs = r.get("subtitle", {}).get("runs", [])
        subtitle = "".join(run.get("text", "") for run in subtitle_runs)

        # Thumbnails
        thumbs = (
            r.get("thumbnailRenderer", {})
            .get("musicThumbnailRenderer", {})
            .get("thumbnail", {})
            .get("thumbnails", [])
        )

        if artist_id and name:
            related.append({
                "id": artist_id,
                "name": name,
                "subtitle": subtitle,
                "thumbnails": thumbs
            })

    return related