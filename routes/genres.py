# routes/genres.py
from __future__ import annotations

from fastapi import APIRouter
from typing import Optional

from services.genre_repo import (
    get_all_genres,
    get_genre_by_slug,
    get_playlists_by_genre,
    get_playlist_by_id,
    get_playlist_tracks,
    get_genre_categories,
)
from services.cache_service import cached
from services.cache_config import CacheType

router = APIRouter(tags=["genres"])


@router.get("/", summary="Lista todos los géneros")
##@cached(CacheType.GENRE_PLAYLISTS, ttl=86400)  # 24 horas
async def list_genres():
    """
    Devuelve todos los géneros disponibles ordenados por sort_order.
    
    Example response:
        {
            "ok": true,
            "genres": [
                {
                    "id": "uuid",
                    "name": "Dance & Electronic",
                    "slug": "dance-electronic",
                    "sort_order": 1
                },
                ...
            ]
        }
    """
    genres = get_all_genres()
    return {"ok": True, "genres": genres}


@router.get("/{slug}/playlists", summary="Playlists de un género")
##@cached(CacheType.GENRE_PLAYLISTS, ttl=86400)
async def list_genre_playlists(
    slug: str,
    category: Optional[str] = None
):
    """
    Devuelve las playlists de un género, opcionalmente filtradas por categoría.
    
    Examples:
        GET /genres/hip-hop/playlists
        GET /genres/decades/playlists?category=1970s
    
    Response:
        {
            "ok": true,
            "genre": {
                "id": "uuid",
                "name": "Hip Hop",
                "slug": "hip-hop",
                "sort_order": 3
            },
            "playlists": [
                {
                    "id": "uuid",
                    "title": "Hip-Hop Classics",
                    "category": null,
                    "track_count": 72,
                    "sort_order": 1
                },
                ...
            ]
        }
    """
    # Verificar que el género existe
    genre = get_genre_by_slug(slug)
    
    if not genre:
        return {"ok": False, "error": "Genre not found"}
    
    # Obtener playlists (filtradas por categoría si se especifica)
    playlists = get_playlists_by_genre(genre["id"], category=category)
    
    return {
        "ok": True,
        "genre": genre,
        "playlists": playlists
    }


@router.get("/{slug}/categories", summary="Categorías disponibles de un género")
#@cached(CacheType.GENRE_PLAYLISTS, ttl=86400)
async def get_categories(slug: str):
    """
    Devuelve las categorías únicas de un género.
    Para géneros sin categorías devuelve un array vacío.
    
    Example: GET /genres/decades/categories
    
    Response:
        {
            "ok": true,
            "genre": {
                "id": "uuid",
                "name": "Decades",
                "slug": "decades"
            },
            "categories": ["1970s", "1980s", "1990s", "2000s", "2010s"]
        }
    """
    genre = get_genre_by_slug(slug)
    
    if not genre:
        return {"ok": False, "error": "Genre not found"}
    
    categories = get_genre_categories(genre["id"])
    
    return {
        "ok": True,
        "genre": genre,
        "categories": categories
    }


# ============================================================================
# PLAYLISTS (ruta separada para independencia)
# ============================================================================

playlists_router = APIRouter(prefix="/playlists", tags=["playlists"])


@playlists_router.get("/{playlist_id}/tracks", summary="Tracks de una playlist")
#@cached(CacheType.GENRE_PLAYLISTS, ttl=86400)
async def get_tracks(
    playlist_id: str,
    limit: Optional[int] = 100
):
    """
    Devuelve los tracks de una playlist con info de la playlist.
    
    Example: GET /playlists/abc-123/tracks?limit=50
    
    Response:
        {
            "ok": true,
            "playlist": {
                "id": "abc-123",
                "title": "Hip-Hop Classics",
                "track_count": 72
            },
            "tracks": [
                {
                    "position": 1,
                    "track_id": "dQw4w9WgXcQ",
                    "title": "Never Gonna Give You Up",
                    "artist": "Rick Astley",
                    "album": "Whenever You Need Somebody",
                    "duration_ms": 213000,
                    "thumbnail_url": "https://...",
                    "artist_id": "..."
                },
                ...
            ]
        }
    """
    # Obtener info de la playlist
    playlist = get_playlist_by_id(playlist_id)
    
    if not playlist:
        return {"ok": False, "error": "Playlist not found"}
    
    # Obtener tracks
    tracks = get_playlist_tracks(playlist_id, limit=limit)
    
    return {
        "ok": True,
        "playlist": {
            "id": playlist["id"],
            "title": playlist["title"],
            "track_count": playlist["track_count"]
        },
        "tracks": tracks
    }