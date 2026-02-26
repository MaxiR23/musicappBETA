from fastapi import APIRouter, Request
from services.weekly_stats_service import get_weekly_summary
from services.supabase_service import db_as_user
from services.auth_utils import get_user_id

router = APIRouter(tags=["stats"])

@router.get("/me/weekly")
def weekly_summary(request: Request, preview: bool = False):
    jwt = request.headers.get("Authorization", "").replace("Bearer ", "")
    db = db_as_user(jwt)
    
    user_id = get_user_id(request)
    if not user_id:
        return {"error": "unauthorized"}
    
    return get_weekly_summary(db, user_id, preview=preview)