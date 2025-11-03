# middlewares/supa_auth.py
import os
from fastapi import Request
from fastapi.responses import JSONResponse
from services.supabase_service import supabase_anon
from services.jwt_utils import decode_jwt

SUPABASE_URL = os.getenv("SUPABASE_URL")
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")

# Prefijos/rutas públicas
PUBLIC_PREFIXES = (
    "/debug",
    "/test",
    "/api/music",
)

PUBLIC_ROUTES = {
    ("GET", "/api"),
    ("GET", "/api/feed/cache/versions"),
    ("GET", "/api/cache/versions"),
}

def _is_public(request: Request) -> bool:
    if request.method == "OPTIONS":
        return True
    
    path = request.url.path
    
    if any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return True
    if (request.method, path) in PUBLIC_ROUTES:
        return True
    
    return False

async def supa_auth(request: Request, call_next):
    # En development, setear user fake si no hay token
    if ENVIRONMENT == "development" and _is_public(request):
        if not request.headers.get("Authorization"):
            request.state.user = {"id": "dev-user-id", "email": "dev@test.com"}
            request.state.jwt = "dev-token"
            return await call_next(request)
    
    if _is_public(request):
        return await call_next(request)

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"error": "missing token"})

    token = auth_header[7:]

    payload = decode_jwt(token) or {}
    iss = payload.get("iss", "")
    iss_host = iss.replace("https://", "").split("/")[0] if iss else None
    env_host = SUPABASE_URL.replace("https://", "").split("/")[0] if SUPABASE_URL else None
    if iss_host and env_host and iss_host != env_host:
        return JSONResponse(status_code=401, content={"error": "invalid token (project mismatch)"})

    try:
        resp = supabase_anon.auth.get_user(token)
        user_obj = getattr(resp, "user", None)
    except Exception as e:
        return JSONResponse(status_code=401, content={"error": "invalid token", "detail": str(e)})

    if not user_obj:
        return JSONResponse(status_code=401, content={"error": "invalid token"})

    request.state.user = {"id": str(user_obj.id), "email": user_obj.email}
    request.state.jwt = token

    return await call_next(request)