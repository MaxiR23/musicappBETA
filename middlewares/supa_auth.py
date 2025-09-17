# middlewares/supa_auth.py
import os
from fastapi import Request
from fastapi.responses import JSONResponse
from services.supabase_service import supabase_anon
from services.jwt_utils import decode_jwt

SUPABASE_URL = os.getenv("SUPABASE_URL")

# Prefijos/rutas públicas (opcional)
PUBLIC_PREFIXES = (
    "/debug",
    "/test",
    "/api/music",   # 👈 todo el módulo music es público
)
  # dejalas pasar sin token
PUBLIC_ROUTES = {
    ("GET", "/api"),        # ejemplo de ping público
    # ("GET", "/api/health"),
}

def _is_public(request: Request) -> bool:
    if request.method == "OPTIONS":  # ✅ preflight CORS SIEMPRE pasa
        return True
    path = request.url.path
    if any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return True
    if (request.method, path) in PUBLIC_ROUTES:
        return True
    return False

async def supa_auth(request: Request, call_next):
    # Si es público (o preflight), no exigir Authorization
    if _is_public(request):
        return await call_next(request)

    # Requiere token
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"error": "missing token"})

    token = auth_header[7:]

    # Validación rápida del 'iss' vs tu proyecto (defensa básica anti cross-project)
    payload = decode_jwt(token) or {}
    iss = payload.get("iss", "")
    iss_host = iss.replace("https://", "").split("/")[0] if iss else None
    env_host = SUPABASE_URL.replace("https://", "").split("/")[0] if SUPABASE_URL else None
    if iss_host and env_host and iss_host != env_host:
        return JSONResponse(status_code=401, content={"error": "invalid token (project mismatch)"})

    # Validar token con Supabase
    try:
        # supabase-py v2: get_user(token) -> objeto con atributo .user
        resp = supabase_anon.auth.get_user(token)
        user_obj = getattr(resp, "user", None)
    except Exception as e:
        # 401 (no 500) si el token no es válido o expiró
        return JSONResponse(status_code=401, content={"error": "invalid token", "detail": str(e)})

    if not user_obj:
        return JSONResponse(status_code=401, content={"error": "invalid token"})

    # Seteamos user y jwt en request.state para el resto de la app
    request.state.user = {"id": str(user_obj.id), "email": user_obj.email}
    request.state.jwt = token

    return await call_next(request)
