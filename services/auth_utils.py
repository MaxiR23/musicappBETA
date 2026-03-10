"""Utilidades de autenticación."""
from fastapi import Request
from services.jwt_utils import decode_jwt

def extract_bearer_token(auth_header: str) -> str:
    """Extrae token de header Authorization. Pura."""
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return ""

def get_user_id_from_state(user: dict | None) -> str | None:
    """Extrae user_id de request.state.user. Pura."""
    if isinstance(user, dict) and user.get("id"):
        return user["id"]
    return None

def get_user_id(request: Request) -> str | None:
    """Extrae user_id del request (state o JWT)."""
    user_id = get_user_id_from_state(getattr(request.state, "user", None))
    if user_id:
        return user_id
    token = extract_bearer_token(request.headers.get("Authorization", ""))
    if not token:
        return None
    claims = decode_jwt(token) or {}
    return claims.get("sub")