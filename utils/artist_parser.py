# utils/artist_parser.py
def parse_top_songs_legacy(section):
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
            if not bid or not name or name in {"•", "&", ","}:
                continue
            artists.append({"id": bid, "name": name})

        artist_name_joined = ", ".join(a["name"] for a in artists) if artists else None
        primary_artist_id = artists[0]["id"] if artists else None

        # Álbum (si está presente)
        album_id = None
        album_title = None 
        try:
            album_runs = (
                r.get("flexColumns", [])[3]
                 .get("musicResponsiveListItemFlexColumnRenderer", {})
                 .get("text", {})
                 .get("runs", [])
            )
            if album_runs:
                album_title = album_runs[0].get("text") or None
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
            "albumTitle": album_title,
            "artistId": primary_artist_id,
            "artistName": artist_name_joined,
            "artists": artists,
            "duration": None,
            "durationSeconds": None,
        })
    return songs


# Nueva función V2
def parse_top_songs_v2(artist_data, yt_client):
    """
    Obtiene las top 10 songs usando get_playlist.
    Requiere artist_data (de get_artist) y yt_client.
    """
    songs_browse_id = artist_data.get("songs", {}).get("browseId")
    top_songs_raw = []
    if songs_browse_id:
        playlist_data = yt_client.get_playlist(songs_browse_id, limit=10)
        top_songs_raw = (playlist_data.get("tracks", []))[:10]
    
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
            "albumId": album_id,
            "albumTitle": album_title,
            "artistId": primary_artist_id,
            "artistName": artist_name,
            "artists": artists,
            "duration": track.get("duration"),
            "durationSeconds": track.get("duration_seconds")
        })
    
    return top_songs_filtered

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
        if subtitle_runs and len(subtitle_runs) > 0:
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

        # Subtitle
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
                "thumbnails": thumbs
            })

    return related