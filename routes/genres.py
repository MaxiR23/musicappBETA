# routes/genres.py
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
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
async def list_genres():
    try:
        genres = get_all_genres()
        return {"ok": True, "genres": genres}
    except Exception as e:
        print(f"[genres][list][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})


@router.get("/{slug}/playlists", summary="Playlists de un género")
async def list_genre_playlists(
    slug: str,
    category: Optional[str] = None
):
    try:
        genre = get_genre_by_slug(slug)
        if not genre:
            return JSONResponse(status_code=404, content={"ok": False, "error": "Genre not found"})
        playlists = get_playlists_by_genre(genre["id"], category=category)
        return {"ok": True, "genre": genre, "playlists": playlists}
    except Exception as e:
        print(f"[genres][playlists][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})


@router.get("/{slug}/categories", summary="Categorías disponibles de un género")
async def get_categories(slug: str):
    try:
        genre = get_genre_by_slug(slug)
        if not genre:
            return JSONResponse(status_code=404, content={"ok": False, "error": "Genre not found"})
        categories = get_genre_categories(genre["id"])
        return {"ok": True, "genre": genre, "categories": categories}
    except Exception as e:
        print(f"[genres][categories][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})


# ============================================================================
# PLAYLISTS (ruta separada para independencia)
# ============================================================================

playlists_router = APIRouter(prefix="/playlists", tags=["playlists"])

@playlists_router.get("/{playlist_id}/tracks", summary="Tracks de una playlist")
async def get_tracks(
    playlist_id: str,
    limit: Optional[int] = 100
):
    try:
        playlist = get_playlist_by_id(playlist_id)
        if not playlist:
            return JSONResponse(status_code=404, content={"ok": False, "error": "Playlist not found"})
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
    except Exception as e:
        print(f"[genres][playlist-tracks][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})