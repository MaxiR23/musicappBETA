from __future__ import annotations
from typing import Any, Dict

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from core.dependencies import get_db
from services.db_protocol import DBClient
from services.new_releases_repo import list_new_releases_cached, build_new_release_item

router = APIRouter()

def _filter_complete(items: list) -> list:
    """Excluye releases sin thumbnail o sin artist_id."""
    return [r for r in items if r.get("thumbnail") and r.get("artist_id")]

@router.get("")
async def get_new_releases(
    limit: int = Query(30, ge=1, le=100),
    db: DBClient = Depends(get_db),
) -> Dict[str, Any]:
    try:
        releases = list_new_releases_cached(db, limit=limit)
        mapped = _filter_complete([build_new_release_item(r) for r in releases])
        return {"ok": True, "count": len(mapped), "releases": mapped}
    except Exception as e:
        print(f"[new_releases][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})