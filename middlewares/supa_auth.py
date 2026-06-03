# middlewares/supa_auth.py
import os
from fastapi import Request
from fastapi.responses import JSONResponse
from services.supabase_service import supabase_anon
from services.jwt_utils import decode_jwt

SUPABASE_URL = os.getenv("SUPABASE_URL")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Rutas publicas SOLO en PRODUCTION (solo cache)
PRODUCTION_PUBLIC_ROUTES = {
    ("GET", "/api"),
    ("GET", "/api/feed/cache/versions"),
    ("GET", "/api/cache/versions"),
    ("GET", "/api/music/play"), # TODO: temporal, remover de aqui.
}

def _is_public(request: Request) -> bool:
    if request.method == "OPTIONS":
        return True
    
    path = request.url.path
    
    if path.startswith("/api/public/"):
        return True
    
    if ENVIRONMENT == "development":
        return True
    
    if (request.method, path) in PRODUCTION_PUBLIC_ROUTES:
        return True
    
    return False

async def supa_auth(request: Request, call_next):
    # En DEVELOPMENT, SIEMPRE usar usuario fake (ignorar tokens completamente)
    if ENVIRONMENT == "development":
        request.state.user = {"id": "dev-user-id", "email": "dev@test.com"}
        request.state.jwt = "dev-token"
        print(f"[DEV] User fake: {request.method} {request.url.path}")
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
        if ENVIRONMENT == "production":
            return JSONResponse(status_code=401, content={"error": "invalid token"})
        return JSONResponse(status_code=401, content={"error": "invalid token", "detail": str(e)})

    if not user_obj:
        return JSONResponse(status_code=401, content={"error": "invalid token"})

    request.state.user = {"id": str(user_obj.id), "email": user_obj.email}
    request.state.jwt = token

    return await call_next(request)