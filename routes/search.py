# routes/search.py
"""Endpoint de búsqueda."""
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from services.search_service import search, get_warm_ids
from services.audio_service import schedule_warm

router = APIRouter()

@router.get("/search")
def search_music(q: str = Query(..., description="Texto a buscar")):
    try:
        result = search(q)
        ids = get_warm_ids(result)
        schedule_warm(ids)
        return result
    except Exception as e:
        print(f"[search][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})