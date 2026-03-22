# utils/artist_parser.py
def parse_top_songs_v2(artist_data, yt_client):
    """
    obtiene las top 10 songs usando get_playlist.
    fallback a results inline + duraciones desde albums (paralelo, cacheado).
    """
    from concurrent.futures import ThreadPoolExecutor

    songs_section = artist_data.get("songs", {})
    songs_browse_id = songs_section.get("browseId")

    if songs_browse_id:
        playlist_data = yt_client.get_playlist(songs_browse_id, limit=10)
        top_songs_raw = (playlist_data.get("tracks", []))[:10]
        duration_map = {}
    else:
        top_songs_raw = (songs_section.get("results", []))[:10]

        album_ids = set()
        for s in top_songs_raw:
            aid = (s.get("album") or {}).get("id")
            if aid:
                album_ids.add(aid)

        duration_map = {}

        def fetch_durations(aid):
            try:
                album_data = yt_client.get_album(aid)
                partial = {}
                for t in album_data.get("tracks", []):
                    title = (t.get("title") or "").strip().lower()
                    if title and t.get("duration_seconds"):
                        partial[title] = {
                            "duration": t.get("duration"),
                            "duration_seconds": t.get("duration_seconds"),
                        }
                return partial
            except Exception:
                return {}

        with ThreadPoolExecutor(max_workers=4) as executor:
            for partial in executor.map(fetch_durations, album_ids):
                duration_map.update(partial)

    top_songs_filtered = []
    for track in top_songs_raw:
        artists_list = track.get("artists", [])
        artists = [{"id": a.get("id"), "name": a.get("name")} for a in artists_list]
        artist_name = ", ".join(a["name"] for a in artists if a.get("name"))
        primary_artist_id = artists[0]["id"] if artists else None

        album = track.get("album") or {}
        album_id = album.get("id")
        album_name = album.get("name")

        thumbs = track.get("thumbnails", [])
        thumbnail = thumbs[-1]["url"] if thumbs else None

        duration = track.get("duration")
        duration_seconds = track.get("duration_seconds")
        if not duration_seconds and duration_map:
            title_key = (track.get("title") or "").strip().lower()
            enriched = duration_map.get(title_key, {})
            duration = enriched.get("duration") or duration
            duration_seconds = enriched.get("duration_seconds") or duration_seconds

        top_songs_filtered.append({
            "id": track.get("videoId"),
            "title": track.get("title"),
            "thumbnail": thumbnail,
            "album_id": album_id,
            "album_name": album_name,
            "artist_id": primary_artist_id,
            "artist_name": artist_name,
            "artists": artists,
            "duration": duration,
            "duration_seconds": duration_seconds,
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