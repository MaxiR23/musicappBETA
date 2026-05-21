from __future__ import annotations

import asyncio
import os
import shutil
import threading
from starlette.background import BackgroundTask

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from core.dependencies import get_current_user_id
from core.rate_limit import limiter
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
@limiter.limit("60/minute")
async def offline_fetch(
    request: Request,
    track_id: str = Path(..., description="ID del track"),
    itag: int = Query(..., description="Format tag"),
    user_id: str = Depends(get_current_user_id),
):
    if not is_allowed(user_id):
        return JSONResponse(status_code=404, content={"detail": "not_found"})

    if not is_valid_itag(itag):
        return JSONResponse(status_code=400, content={"error": "invalid_itag"})

    abort_event = threading.Event()

    async def _watch_disconnect():
        try:
            while not abort_event.is_set():
                if await request.is_disconnected():
                    abort_event.set()
                    return
                await asyncio.sleep(0.5)
        except Exception:
            abort_event.set()

    watcher = asyncio.create_task(_watch_disconnect())

    try:
        result = await asyncio.to_thread(fetch_audio, track_id, user_id, itag, abort_event)
    finally:
        abort_event.set()
        watcher.cancel()
        try:
            await watcher
        except (asyncio.CancelledError, Exception):
            pass

    if "error" in result:
        if result["error"] == "aborted":
            return JSONResponse(status_code=499, content=result)
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