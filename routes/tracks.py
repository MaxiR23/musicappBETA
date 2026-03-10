from __future__ import annotations

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse

from services.track_service import get_lyrics, get_related, get_related_raw, get_up_next

router = APIRouter()

@router.get("/tracks/{track_id}/lyrics")
def get_track_lyrics(track_id: str = Path(...)):
    try:
        res = get_lyrics(track_id)
        if not res.get("ok"):
            return JSONResponse(status_code=404, content=res)
        return res
    except Exception as e:
        print(f"[tracks][lyrics][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})

@router.get("/tracks/{track_id}/related")
def get_track_related(track_id: str = Path(...)):
    try:
        res = get_related(track_id)
        if not res.get("ok"):
            return JSONResponse(status_code=404, content=res)
        return res
    except Exception as e:
        print(f"[tracks][related][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})

@router.get("/tracks/{track_id}/related-raw")
def get_track_related_raw(track_id: str = Path(...)):
    try:
        res = get_related_raw(track_id)
        if not res.get("ok"):
            return JSONResponse(status_code=404, content=res)
        return res
    except Exception as e:
        print(f"[tracks][related-raw][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})

@router.get("/tracks/{track_id}/upnext")
def get_track_upnext(track_id: str = Path(...)):
    try:
        res = get_up_next(track_id)
        if not res.get("ok"):
            return JSONResponse(status_code=404, content=res)
        return res
    except Exception as e:
        print(f"[tracks][upnext][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})