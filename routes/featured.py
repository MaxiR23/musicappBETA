from __future__ import annotations
from typing import Any, Dict

from fastapi import APIRouter, Depends
from fastapi.responses import ORJSONResponse, JSONResponse

from core.dependencies import get_db, get_current_user_id
from services.db_protocol import DBClient
from services.featured_service import get_featured_new_release_cached

router = APIRouter()

@router.get("", response_class=ORJSONResponse)
async def get_featured_release(
    user_id: str = Depends(get_current_user_id),
    db: DBClient = Depends(get_db),
) -> Dict[str, Any]:
    try:
        featured = get_featured_new_release_cached(db, user_id)
        if not featured:
            return {"ok": True, "featured": None}
        return {"ok": True, "featured": featured}
    except Exception as e:
        print(f"[featured][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})