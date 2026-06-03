# INFO: Validates X-Internal-API-Key on /api/public/* in production; passes everything else through.
import os
import secrets
from fastapi import Request
from fastapi.responses import JSONResponse

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
INTERNAL_SHARE_API_KEY = os.getenv("INTERNAL_SHARE_API_KEY")

async def internal_key_guard(request: Request, call_next):
    path = request.url.path

    if request.method == "OPTIONS" or not path.startswith("/api/public/"):
        return await call_next(request)

    if ENVIRONMENT == "development":
        return await call_next(request)

    provided = request.headers.get("X-Internal-API-Key")
    if (
        not INTERNAL_SHARE_API_KEY
        or not provided
        or not secrets.compare_digest(provided, INTERNAL_SHARE_API_KEY)
    ):
        return JSONResponse(status_code=403, content={"error": "forbidden"})

    return await call_next(request)