from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse

from core.dependencies import get_user_db, get_service_db, get_current_user_id
from services.db_protocol import DBClient
from services.likes_service import (
    like_track,
    unlike_track,
    get_likes,
    get_likes_sync,
)

router = APIRouter(tags=["likes"])

@router.post("/")
async def like_track_route(
    body: dict = Body(...),
    db: DBClient = Depends(get_user_db),
    service_db: DBClient = Depends(get_service_db),
    user_id: str = Depends(get_current_user_id),
):
    track_id = body.get("track_id")
    if not track_id:
        return JSONResponse(status_code=400, content={"error": "track_id_required"})
    try:
        result = like_track(db, service_db, user_id, track_id, body)
        return {"ok": True, **result}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "db_error", "detail": str(e)})

@router.delete("/{track_id}")
async def unlike_track_route(
    track_id: str,
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    try:
        unlike_track(db, user_id, track_id)
        return {"ok": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "db_error", "detail": str(e)})

@router.get("/")
async def get_likes_route(
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    try:
        return get_likes(db, user_id)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "db_error", "detail": str(e)})

@router.get("/sync")
async def get_likes_sync_route(
    since: str = Query(..., description="ISO timestamp for delta sync"),
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    try:
        return get_likes_sync(db, user_id, since)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "db_error", "detail": str(e)})