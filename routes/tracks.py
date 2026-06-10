from __future__ import annotations

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse

from services.track_service import get_credits, get_lyrics, get_related, get_related_raw, get_up_next

router = APIRouter()

# Explicit mapping of service-layer failure reasons to HTTP status codes.
# Unknown reasons default to 502 so new service failures are not hidden as 200.
_REASON_STATUS: dict[str, int] = {
    "error": 502,
    "invalid_id": 422,
    "no_lyrics": 200,
    "no_credits": 200,
    "no_watch_playlist": 200,
    "no_browse_id": 200,
    "no_tracks": 200,
}

def _status_for(res: dict) -> int:
    return _REASON_STATUS.get(res.get("reason", ""), 502)


@router.get("/tracks/{track_id}/lyrics")
def get_track_lyrics(track_id: str = Path(...)):
    try:
        res = get_lyrics(track_id)
        if not res.get("ok"):
            return JSONResponse(status_code=_status_for(res), content=res)  # 200: data not found for existing resource
        return res
    except Exception as e:
        print(f"[tracks][lyrics][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})

@router.get("/tracks/{track_id}/related")
def get_track_related(track_id: str = Path(...)):
    try:
        res = get_related(track_id)
        if not res.get("ok"):
            return JSONResponse(status_code=_status_for(res), content=res)  # 200: data not found for existing resource
        return res
    except Exception as e:
        print(f"[tracks][related][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})

@router.get("/tracks/{track_id}/related-raw")
def get_track_related_raw(track_id: str = Path(...)):
    try:
        res = get_related_raw(track_id)
        if not res.get("ok"):
            return JSONResponse(status_code=_status_for(res), content=res)  # 200: data not found for existing resource
        return res
    except Exception as e:
        print(f"[tracks][related-raw][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})

@router.get("/tracks/{track_id}/upnext")
def get_track_upnext(track_id: str = Path(...)):
    try:
        res = get_up_next(track_id)
        if not res.get("ok"):
            return JSONResponse(status_code=_status_for(res), content=res)  # 200: data not found for existing resource
        return res
    except Exception as e:
        print(f"[tracks][upnext][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})

@router.get("/tracks/{track_id}/credits")
def get_track_credits(track_id: str = Path(...)):
    try:
        res = get_credits(track_id)
        if not res.get("ok"):
            return JSONResponse(status_code=_status_for(res), content=res)  # 200: data not found for existing resource
        return res
    except Exception as e:
        print(f"[tracks][credits][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})
