# routes/tracks.py
"""Endpoints de tracks: lyrics, related, upnext."""
from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse
from services.track_service import get_lyrics, get_related, get_related_raw, get_upnext

router = APIRouter()

@router.get("/tracks/{track_id}/lyrics")
def get_track_lyrics(track_id: str = Path(...)):
    res = get_lyrics(track_id)
    if not res.get("ok"):
        return JSONResponse(status_code=404, content=res)
    return res

@router.get("/tracks/{track_id}/related")
def get_track_related(track_id: str = Path(...)):
    res = get_related(track_id)
    if not res.get("ok"):
        return JSONResponse(status_code=404, content=res)
    return res

@router.get("/tracks/{track_id}/related-raw")
def get_track_related_raw(track_id: str = Path(...)):
    res = get_related_raw(track_id)
    if not res.get("ok"):
        return JSONResponse(status_code=404, content=res)
    return res

@router.get("/tracks/{track_id}/upnext")
def get_track_upnext(track_id: str = Path(...)):
    res = get_upnext(track_id)
    if not res.get("ok"):
        return JSONResponse(status_code=404, content=res)
    return res