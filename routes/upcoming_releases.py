from __future__ import annotations
from typing import Any, Dict

from fastapi import APIRouter, Depends, Query
from fastapi.responses import ORJSONResponse, JSONResponse

from core.dependencies import get_db
from services.db_protocol import DBClient
from services.upcoming_releases_repo import list_upcoming_releases_cached, build_upcoming_item, list_upcoming_30d_cached

router = APIRouter()

def _filter_complete(items: list) -> list:
    """Excluye releases sin thumbnail o sin artist_id."""
    return [r for r in items if r.get("thumbnail") and r.get("artist_id")]

@router.get("", response_class=ORJSONResponse)
async def get_upcoming_releases(
    include_tba: bool = Query(True, description="Incluir releases TBA"),
    limit: int = Query(50, ge=1, le=100, description="Límite de resultados"),
    db: DBClient = Depends(get_db),
) -> Dict[str, Any]:
    try:
        releases = list_upcoming_releases_cached(db, include_tba=include_tba, limit=limit)
        mapped = _filter_complete([build_upcoming_item(r) for r in releases])
        return {"ok": True, "count": len(mapped), "releases": mapped}
    except Exception as e:
        print(f"[upcoming_releases][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})

@router.get("/next", response_class=ORJSONResponse)
async def get_upcoming_next(
    db: DBClient = Depends(get_db),
) -> Dict[str, Any]:
    try:
        releases = list_upcoming_30d_cached(db)
        mapped = _filter_complete([build_upcoming_item(r) for r in releases])
        return {"ok": True, "count": len(mapped), "releases": mapped}
    except Exception as e:
        print(f"[upcoming_releases/next][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})