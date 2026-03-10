"""Dependencias compartidas para FastAPI."""
from fastapi import Request, HTTPException

from services.db_protocol import DBClient
from services.supabase_service import supabase_service as sb, db_as_user, supabase_service
from services.auth_utils import get_user_id


def get_db() -> DBClient:
    """Cliente DB con service role. Para operaciones sin RLS."""
    return sb

def get_user_db(request: Request) -> DBClient:
    """Cliente DB con RLS del usuario. Para operaciones sobre datos propios."""
    jwt = request.headers.get("Authorization", "").replace("Bearer ", "")
    return db_as_user(jwt)

def get_service_db() -> DBClient:
    """Cliente DB con service role explícito. Para operaciones privilegiadas."""
    return supabase_service

def get_current_user_id(request: Request) -> str:
    """Extrae user_id del request. Lanza 401 si no autenticado."""
    user_id = get_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user_id

def get_optional_user_id(request: Request) -> str | None:
    """Extrae user_id si existe, None si no."""
    return get_user_id(request)