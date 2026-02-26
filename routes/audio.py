"""
Endpoints de audio: play, prefetch, warm
Incluye lógica de extracción y streaming (delegada a services/audio_service.py)
"""
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

@router.get("/play")
def play_song(request: Request, id: str = Query(...), redir: int = Query(2)):
    try:
        data = get_audio_info(id)
        audio_url = data["direct_url"]

        parsed_qs = urllib.parse.parse_qs(urllib.parse.urlsplit(audio_url).query)
        has_ip_param = "ip" in parsed_qs and parsed_qs["ip"] and parsed_qs["ip"][0]
        if redir == 1 and has_ip_param:
            redir = 2

        if redir == 2:
            range_header = request.headers.get("range")
            return stream_from_url(audio_url, range_header)

        if redir == 1:
            return RedirectResponse(url=audio_url, status_code=307)

        return JSONResponse({"url": audio_url})

    except Exception as e:
        return JSONResponse(status_code=502, content={"error": "no_stream", "detail": str(e), "id": id})

@router.post("/prefetch")
def prefetch_songs(payload: dict = Body(...)):
    if not WARM_ENABLED:
        return {"ok": True, "scheduled": 0}
    raw_ids = payload.get("ids", []) or []
    ids = [str(i).strip() for i in raw_ids if i][:60]
    schedule_warm(ids)
    return {"ok": True, "scheduled": min(len(ids), get_warm_burst())}

@router.post("/warm")
def warm_ids(payload: dict = Body(...)):
    if not WARM_ENABLED:
        return {"ok": True, "scheduled": 0}
    ids = [str(i).strip() for i in (payload.get("ids") or []) if i]
    limit = int(payload.get("limit") or get_warm_burst())
    schedule_warm(ids[:limit])
    return {"ok": True, "scheduled": min(len(ids), limit)}