# services/users_repo.py
from __future__ import annotations
from typing import List
from services.supabase_service import supabase_service as sb

def get_all_user_ids() -> List[str]:
    """
    Obtiene todos los UUIDs de la tabla user_ids
    """
    res = sb.table("user_ids").select("id").execute()
    data = getattr(res, "data", None) or []
    return [row["id"] for row in data if row.get("id")]