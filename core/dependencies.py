"""Dependencias compartidas para FastAPI."""
from fastapi import Request, HTTPException, Depends

from services.db_protocol import DBClient
from services.supabase_service import supabase_service as sb, db_as_user, supabase_service
from services.auth_utils import get_user_id
from services.profile_service import get_profile_by_id
from models.profile import Profile, has_role_or_higher

def get_db() -> DBClient:
    """Cliente DB con service role. Para operaciones sin RLS."""
    return sb

def get_user_db(request: Request) -> DBClient:
    """Cliente DB con RLS del usuario. Para operaciones sobre datos propios.

    El ciclo de vida del client lo maneja el cache LRU de db_as_user;
    no se cierra por request (cerrarlo rompe el cache).
    """
    jwt = request.headers.get("Authorization", "").replace("Bearer ", "")
    return db_as_user(jwt)

def get_service_db() -> DBClient:
    """Cliente DB con service role explicito. Para operaciones privilegiadas."""
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

def get_current_profile(
    user_id: str = Depends(get_current_user_id),
    db: DBClient = Depends(get_service_db),
) -> Profile:
    """Obtiene el profile del usuario actual. Lanza 404 si no existe."""
    profile = get_profile_by_id(db, user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="profile_not_found")
    return profile

def require_role(min_role: str):
    """
    Factory que devuelve una dependency. Protege endpoints por rol.

    Uso:
        @router.get("/admin/stuff")
        def admin_stuff(profile: Profile = Depends(require_role("admin"))):
            ...
    """
    def checker(profile: Profile = Depends(get_current_profile)) -> Profile:
        if not has_role_or_higher(profile.role, min_role):
            raise HTTPException(
                status_code=403,
                detail=f"insufficient_permissions: requires {min_role} or higher",
            )
        return profile

    return checker