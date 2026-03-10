# routes/upcoming_releases.py
from __future__ import annotations
from typing import Any, Dict

from fastapi import APIRouter, Query
from fastapi.responses import ORJSONResponse, JSONResponse
from services.upcoming_releases_repo import list_upcoming_releases_cached

router = APIRouter()

@router.get("", response_class=ORJSONResponse)
async def get_upcoming_releases(
    include_tba: bool = Query(True, description="Incluir releases TBA"),
    limit: int = Query(50, ge=1, le=100, description="Límite de resultados")
) -> Dict[str, Any]:
    """
    GET /upcoming-releases

    Retorna releases futuros (desde hoy en adelante).
    El caché expira automáticamente cuando hay un nuevo release.
    """
    try:
        releases = list_upcoming_releases_cached(include_tba=include_tba, limit=limit)
        return {
            "ok": True,
            "count": len(releases),
            "releases": releases
        }
    except Exception as e:
        print(f"[upcoming_releases][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})