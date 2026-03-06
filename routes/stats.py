from fastapi import APIRouter, Request, Query
from typing import Optional
from services.weekly_stats_service import get_weekly_summary
from services.monthly_stats_service import get_monthly_summary
from services.supabase_service import db_as_user
from services.auth_utils import get_user_id

router = APIRouter(tags=["stats"])

@router.get("/weekly")
def weekly_summary(
    request: Request, 
    include: Optional[str] = None,  # "artists" o "artists,albums,tracks"
    limit: Optional[int] = None, # límite por tipo
):
    jwt = request.headers.get("Authorization", "").replace("Bearer ", "")
    db = db_as_user(jwt)
    
    user_id = get_user_id(request)
    if not user_id:
        return {"error": "unauthorized"}
    
    return get_weekly_summary(db, user_id, include=include, limit=limit)

@router.get("/monthly")
def monthly(
    request: Request,
    include: Optional[str] = None,
    limit: Optional[int] = None,
):
    jwt = request.headers.get("Authorization", "").replace("Bearer ", "")
    db = db_as_user(jwt)
    user_id = get_user_id(request)
    if not user_id:
        return {"error": "unauthorized"}
    return get_monthly_summary(db, user_id, include=include, limit=limit)