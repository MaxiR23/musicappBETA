from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from typing import Optional
from services.weekly_stats_service import get_weekly_summary
from services.monthly_stats_service import get_monthly_summary
from services.supabase_service import db_as_user
from services.auth_utils import get_user_id

router = APIRouter(tags=["stats"])

@router.get("/weekly")
def weekly_summary(
    request: Request, 
    include: Optional[str] = None,
    limit: Optional[int] = None,
):
    jwt = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_id = get_user_id(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"ok": False, "error": "unauthorized"})

    try:
        db = db_as_user(jwt)
        return get_weekly_summary(db, user_id, include=include, limit=limit)
    except Exception as e:
        print(f"[stats][weekly][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})

@router.get("/monthly")
def monthly(
    request: Request,
    include: Optional[str] = None,
    limit: Optional[int] = None,
):
    jwt = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_id = get_user_id(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"ok": False, "error": "unauthorized"})

    try:
        db = db_as_user(jwt)
        return get_monthly_summary(db, user_id, include=include, limit=limit)
    except Exception as e:
        print(f"[stats][monthly][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})