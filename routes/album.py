"""Endpoints de albums."""
from fastapi import APIRouter, Query, Path
from fastapi.responses import JSONResponse

from services.album_service import get_album
from services.audio_service import schedule_warm, get_warm_burst

router = APIRouter()

# ── HELPERS ──────────────────────────────────────────────
def _handle_album_request(album_id: str):
    """Lógica común para obtener album."""
    try:
        payload = get_album(album_id)
        if isinstance(payload, dict) and payload.get("error"):
            return JSONResponse(status_code=502, content=payload)
        ids = [t.get("videoId") for t in payload.get("tracks", []) if t.get("videoId")]
        schedule_warm(ids[:get_warm_burst()])
        return payload
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": "service_unavailable", "detail": str(e)})

# ── ENDPOINTS ────────────────────────────────────────────
@router.get("/album")
def get_album_q(id: str = Query(...)):
    return _handle_album_request(id)

@router.get("/album/{id}")
def get_album_p(id: str = Path(...)):
    return _handle_album_request(id)