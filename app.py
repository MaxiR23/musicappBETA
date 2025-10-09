# app.py
import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from routes import index, music, playlists, feed, debug
from middlewares.supa_auth import supa_auth
from middlewares.cors_headers import add_cors_middleware

# Crear la app
app = FastAPI()

# CORS siempre primero (usa el de middlewares/cors_headers.py)
add_cors_middleware(app)

# Middleware de auth siempre activo (para debug)
ENV = os.getenv("NODE_ENV", "development")
print(f"🚀 Iniciando FastAPI con ENV={ENV}")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"➡️ Request recibido: {request.method} {request.url}")
    response = await call_next(request)
    print(f"⬅️ Response enviado: {response.status_code} {request.url}")
    return response

# También tu middleware supa_auth
app.middleware("http")(supa_auth)
print("🔐 Middleware supa_auth registrado")

# 🚨 Global exception handler
logger = logging.getLogger("uvicorn.error")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"❌ Unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "detail": str(exc)},
    )

# Rutas principales
app.include_router(index.router, prefix="/api")
app.include_router(music.router, prefix="/api/music")
app.include_router(playlists.router, prefix="/api/playlists")
app.include_router(feed.router, prefix="/api/feed")

# Rutas de debug/test (solo en desarrollo)
if ENV != "production":
    app.include_router(debug.router, prefix="/debug")
    app.include_router(debug.router, prefix="/test")