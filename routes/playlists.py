from fastapi import APIRouter, Body, Depends, Path
from fastapi.responses import JSONResponse

from core.dependencies import get_user_db, get_service_db, get_current_user_id
from services.db_protocol import DBClient
from services.playlist_service import (
    create_playlist,
    get_playlists,
    get_playlist_by_id,
    update_playlist,
    delete_playlist,
    add_track,
    remove_track,
    move_track,
)

router = APIRouter(tags=["playlists"])

# ── PLAYLISTS ──────────────────────────────────────────────────────────────────
@router.post("/")
async def create_playlist_route(
    body: dict = Body(...),
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    title = body.get("title")
    if not title:
        return JSONResponse(status_code=400, content={"error": "title_required"})
    try:
        return create_playlist(db, user_id, title, body.get("description"), body.get("is_public", False))
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "db_error", "detail": str(e)})

@router.get("/")
async def get_playlists_route(
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    try:
        return get_playlists(db, user_id)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "db_error", "detail": str(e)})

@router.get("/{playlist_id}")
async def get_playlist_by_id_route(
    playlist_id: str,
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    try:
        return get_playlist_by_id(db, user_id, playlist_id)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "db_error", "detail": str(e)})

@router.patch("/{playlist_id}")
async def update_playlist_route(
    playlist_id: str,
    body: dict = Body(...),
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    title = body.get("title")
    if not title:
        return JSONResponse(status_code=400, content={"error": "title_required"})
    try:
        return update_playlist(db, user_id, playlist_id, title, body.get("description"), body.get("is_public", False))
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "db_error", "detail": str(e)})

@router.delete("/{playlist_id}")
async def delete_playlist_route(
    playlist_id: str,
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    try:
        deleted = delete_playlist(db, user_id, playlist_id)
        return {"ok": True, "deleted": deleted}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "db_error", "detail": str(e)})

# ── TRACKS ─────────────────────────────────────────────────────────────────────
@router.post("/{playlist_id}/tracks")
async def add_track_route(
    playlist_id: str,
    body: dict = Body(...),
    db: DBClient = Depends(get_user_db),
    service_db: DBClient = Depends(get_service_db),
    user_id: str = Depends(get_current_user_id),
):
    track_id = body.get("track_id")
    if not track_id:
        return JSONResponse(status_code=400, content={"error": "track_id_required"})
    try:
        result = add_track(db, service_db, user_id, playlist_id, track_id, body)
        return {"ok": True, **result}
    except ValueError as e:
        if "track_already_in_playlist" in str(e):
            return JSONResponse(status_code=409, content={"error": "track_already_in_playlist"})
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "db_error", "detail": str(e)})

@router.delete("/{playlist_id}/tracks/{track_id}")
async def remove_track_route(
    playlist_id: str,
    track_id: str,
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    try:
        remove_track(db, user_id, playlist_id, track_id)
        return {"ok": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "db_error", "detail": str(e)})

@router.post("/{playlist_id}/move-track")
def move_track_route(
    playlist_id: str = Path(...),
    body: dict = Body(...),
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    old_index = body.get("old_position")
    new_index = body.get("new_position")

    if not isinstance(old_index, int) or not isinstance(new_index, int) \
       or old_index < 1 or new_index < 1:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid_params"})
    try:
        return move_track(db, user_id, playlist_id, old_index, new_index)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "move_failed", "detail": str(e)})