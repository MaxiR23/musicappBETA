from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from core.dependencies import get_user_db, get_current_user_id
from services.db_protocol import DBClient
from services.weekly_stats_service import get_weekly_summary
from services.monthly_stats_service import get_monthly_summary

router = APIRouter(tags=["stats"])

@router.get("/weekly")
def weekly_summary(
    include: Optional[str] = None,
    limit: Optional[int] = None,
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    try:
        return get_weekly_summary(db, user_id, include=include, limit=limit)
    except Exception as e:
        print(f"[stats][weekly][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})

@router.get("/monthly")
def monthly_summary(
    include: Optional[str] = None,
    limit: Optional[int] = None,
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    try:
        return get_monthly_summary(db, user_id, include=include, limit=limit)
    except Exception as e:
        print(f"[stats][monthly][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})