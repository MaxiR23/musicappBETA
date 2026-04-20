from __future__ import annotations

import os
import shutil
from starlette.background import BackgroundTask

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import FileResponse, JSONResponse

from core.dependencies import get_current_user_id
from services.offline_service import (
    OFFLINE_USERS,
    is_allowed,
    is_valid_itag,
    fetch_audio,
    media_type_for_itag,
    extension_for_itag,
)

router = APIRouter()

@router.get("/offline/fetch/{track_id}")
def offline_fetch(
    track_id: str = Path(..., description="ID del track"),
    itag: int = Query(..., description="Format tag"),
    user_id: str = Depends(get_current_user_id),
):
    if not is_allowed(user_id):
        return JSONResponse(status_code=404, content={"detail": "not_found"})

    if not is_valid_itag(itag):
        return JSONResponse(status_code=400, content={"error": "invalid_itag"})

    result = fetch_audio(track_id, user_id, itag)

    if "error" in result:
        status = {
            "not_found": 404,
            "no_cookies": 503,
            "fetch_failed": 502,
            "timeout": 504,
            "service_unavailable": 502,
        }.get(result["error"], 500)
        return JSONResponse(status_code=status, content=result)

    return FileResponse(
        path=result["path"],
        media_type=media_type_for_itag(itag),
        filename=f"{track_id}.{extension_for_itag(itag)}",
        background=BackgroundTask(shutil.rmtree, os.path.dirname(result["path"]), ignore_errors=True),
    )