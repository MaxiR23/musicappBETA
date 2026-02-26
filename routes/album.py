"""Endpoints de albums."""
from fastapi import APIRouter, Query, Path
from services.album_service import get_album
from services.audio_service import schedule_warm, get_warm_burst

router = APIRouter()

@router.get("/album")
def get_album_q(id: str = Query(...)):
    payload = get_album(id)
    # Warming de tracks
    ids = [t.get("videoId") for t in payload.get("tracks", []) if t.get("videoId")]
    schedule_warm(ids[:get_warm_burst()])
    return payload

@router.get("/album/{id}")
def get_album_p(id: str = Path(...)):
    payload = get_album(id)
    # Warming de tracks
    ids = [t.get("videoId") for t in payload.get("tracks", []) if t.get("videoId")]
    schedule_warm(ids[:get_warm_burst()])
    return payload