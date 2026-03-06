# utils/related_parser.py
"""Parser para normalizar datos de related tracks."""

def _best_thumbnail(thumbs: list) -> str | None:
    """Devuelve la URL del mejor thumbnail."""
    if not thumbs:
        return None
    return thumbs[-1].get("url") if thumbs else None

def _extract_artists(artists_raw: list) -> tuple[str | None, str | None, list]:
    """
    Extrae info de artistas.
    Retorna: (artist_name, artist_id, artists_list)
    """
    artists = artists_raw or []
    artist_names = [a.get("name") for a in artists if a.get("name")]
    artist_ids = [a.get("id") for a in artists if a.get("id")]
    
    return (
        ", ".join(artist_names) if artist_names else None,
        artist_ids[0] if artist_ids else None,
        [{"name": a.get("name"), "id": a.get("id")} for a in artists],
    )

def _normalize_track(track: dict) -> dict:
    """Normaliza un track de la sección 'You might also like'."""
    artist_name, artist_id, artists = _extract_artists(track.get("artists"))
    album = track.get("album") or {}
    
    return {
        "track_id": track.get("videoId"),
        "title": track.get("title"),
        "thumbnail": _best_thumbnail(track.get("thumbnails")),
        "is_explicit": track.get("isExplicit", False),
        "artist_name": artist_name,
        "artist_id": artist_id,
        "artists": artists,
        "album_name": album.get("name"),
        "album_id": album.get("id"),
    }

def _normalize_artist(artist: dict) -> dict:
    """Normaliza un artista de la sección 'Similar artists'."""
    return {
        "artist_id": artist.get("browseId"),
        "name": artist.get("title"),
        "subscribers": artist.get("subscribers"),
        "thumbnail": _best_thumbnail(artist.get("thumbnails")),
    }

def _normalize_album(album: dict) -> dict:
    """Normaliza un álbum/EP de secciones de artista."""
    artist_name, artist_id, artists = _extract_artists(album.get("artists"))
    
    return {
        "album_id": album.get("browseId"),
        "audio_playlist_id": album.get("audioPlaylistId"),
        "title": album.get("title"),
        "type": album.get("type"),
        "year": album.get("year"),
        "thumbnail": _best_thumbnail(album.get("thumbnails")),
        "is_explicit": album.get("isExplicit", False),
        "artist_name": artist_name,
        "artist_id": artist_id,
        "artists": artists,
    }

def parse_related_sections(sections: list) -> list:
    """
    Normaliza todas las secciones de related.
    Detecta el tipo de contenido por los campos presentes.
    """
    if not sections or not isinstance(sections, list):
        return []
    
    out = []
    for section in sections:
        if not isinstance(section, dict):
            continue
            
        title = section.get("title", "")
        contents = section.get("contents")
        
        # Si contents es string (ej: "About the artist"), manejarlo aparte
        if isinstance(contents, str):
            out.append({
                "title": title,
                "section_type": "text",
                "contents": contents,
            })
            continue
        
        if not isinstance(contents, list):
            continue
        
        normalized_contents = []
        section_type = "unknown"
        
        for item in contents:
            if not isinstance(item, dict):
                continue
            if item.get("videoId"):
                section_type = "tracks"
                normalized_contents.append(_normalize_track(item))
            elif item.get("subscribers") is not None:
                section_type = "artists"
                normalized_contents.append(_normalize_artist(item))
            elif item.get("audioPlaylistId") or item.get("type"):
                section_type = "albums"
                normalized_contents.append(_normalize_album(item))
            else:
                normalized_contents.append(item)
        
        out.append({
            "title": title,
            "section_type": section_type,
            "contents": normalized_contents,
        })
    
    return out