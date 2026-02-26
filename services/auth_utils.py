# services/auth_utils.py
"""Utilidades de autenticación."""
from fastapi import Request
from services.jwt_utils import decode_jwt

def get_user_id(request: Request) -> str | None:
    """Extrae user_id del request (state o JWT)."""
    user = getattr(request.state, "user", None)
    if isinstance(user, dict) and user.get("id"):
        return user["id"]
    auth = request.headers.get("Authorization", "")
    token = auth.split(" ", 1)[1].strip() if auth.lower().startswith("bearer ") else ""
    claims = decode_jwt(token) or {}
    return claims.get("sub")