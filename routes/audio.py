"""Endpoints de audio: play, prefetch, warm"""
import urllib.parse

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from services.audio_service import (
    get_audio_info,
    stream_from_url,
    schedule_warm,
    get_warm_burst,
    WARM_ENABLED,
)

router = APIRouter()

# ── HELPERS ──────────────────────────────────────────────
def _has_ip_param(url: str) -> bool:
    """Verifica si la URL tiene parámetro ip."""
    parsed_qs = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    return bool(parsed_qs.get("ip", [None])[0])

def _extract_and_limit_ids(raw_ids: list, limit: int) -> list:
    """Extrae y limita IDs."""
    return [str(i).strip() for i in raw_ids if i][:limit]

# ── ENDPOINTS ────────────────────────────────────────────
@router.get("/play")
def play_song(request: Request, id: str = Query(...), redir: int = Query(2)):
    try:
        data = get_audio_info(id)
        audio_url = data["direct_url"]

        if redir == 1 and _has_ip_param(audio_url):
            redir = 2

        if redir == 2:
            return stream_from_url(audio_url, request.headers.get("range"))

        if redir == 1:
            return RedirectResponse(url=audio_url, status_code=307)

        return JSONResponse({"url": audio_url})

    except Exception as e:
        return JSONResponse(status_code=502, content={"error": "no_stream", "detail": str(e), "id": id})

@router.post("/prefetch")
def prefetch_songs(payload: dict = Body(...)):
    if not WARM_ENABLED:
        return {"ok": True, "scheduled": 0}
    ids = _extract_and_limit_ids(payload.get("ids") or [], 60)
    schedule_warm(ids)
    return {"ok": True, "scheduled": min(len(ids), get_warm_burst())}

@router.post("/warm")
def warm_ids(payload: dict = Body(...)):
    if not WARM_ENABLED:
        return {"ok": True, "scheduled": 0}
    limit = int(payload.get("limit") or get_warm_burst())
    ids = _extract_and_limit_ids(payload.get("ids") or [], limit)
    schedule_warm(ids)
    return {"ok": True, "scheduled": len(ids)}