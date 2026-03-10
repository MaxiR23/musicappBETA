from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from core.dependencies import get_db
from services.db_protocol import DBClient
from services.genre_repo import (
    get_all_genres,
    get_genre_by_slug,
    get_playlists_by_genre,
    get_playlist_by_id,
    get_playlist_tracks,
    get_genre_categories,
)

router = APIRouter(tags=["genres"])
playlists_router = APIRouter(prefix="/playlists", tags=["playlists"])

# ── GENRES ───────────────────────────────────────────────
@router.get("/", summary="Lista todos los géneros")
async def list_genres(db: DBClient = Depends(get_db)):
    try:
        return {"ok": True, "genres": get_all_genres(db)}
    except Exception as e:
        print(f"[genres][list][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})

@router.get("/{slug}/playlists", summary="Playlists de un género")
async def list_genre_playlists(
    slug: str,
    category: Optional[str] = None,
    db: DBClient = Depends(get_db),
):
    try:
        genre = get_genre_by_slug(db, slug)
        if not genre:
            return JSONResponse(status_code=404, content={"ok": False, "error": "genre_not_found"})
        return {"ok": True, "genre": genre, "playlists": get_playlists_by_genre(db, genre["id"], category=category)}
    except Exception as e:
        print(f"[genres][playlists][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})

@router.get("/{slug}/categories", summary="Categorías disponibles de un género")
async def get_categories(slug: str, db: DBClient = Depends(get_db)):
    try:
        genre = get_genre_by_slug(db, slug)
        if not genre:
            return JSONResponse(status_code=404, content={"ok": False, "error": "genre_not_found"})
        return {"ok": True, "genre": genre, "categories": get_genre_categories(db, genre["id"])}
    except Exception as e:
        print(f"[genres][categories][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})

# ── PLAYLISTS ─────────────────────────────────────────────
@playlists_router.get("/{playlist_id}/tracks", summary="Tracks de una playlist")
async def get_tracks(
    playlist_id: str,
    limit: Optional[int] = 100,
    db: DBClient = Depends(get_db),
):
    try:
        playlist = get_playlist_by_id(db, playlist_id)
        if not playlist:
            return JSONResponse(status_code=404, content={"ok": False, "error": "playlist_not_found"})
        return {
            "ok": True,
            "playlist": {
                "id": playlist["id"],
                "title": playlist["title"],
                "track_count": playlist["track_count"],
            },
            "tracks": get_playlist_tracks(db, playlist_id, limit=limit),
        }
    except Exception as e:
        print(f"[genres][playlist-tracks][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})