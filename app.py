# app.py
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, ORJSONResponse
from routes import cache, index, music, playlists, feed, debug, genres, upcoming_releases
from middlewares.supa_auth import supa_auth
from middlewares.cors_headers import add_cors_middleware

# Lifespan: pre-warm en startup (sin deprecations)
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # importa aquí para no cargar nada si no levanta la app
        from routes.music import _ytm, _ydl_global
        _ytm()         # inicializa InnerTube("WEB_REMIX") global
        _ydl_global()  # inicializa yt_dlp global
        print("[lifespan] warmed: InnerTube + yt_dlp")
    except Exception as e:
        print(f"[lifespan][warm][WARN] {e}")
    yield
    # opcional y liviano: cierre prolijo de recursos
    try:
        from routes.music import _WARM_EXECUTOR, _SESSION_SHORT, _SESSION_STREAM, _YDL_GLOBAL
        if _WARM_EXECUTOR:
            _WARM_EXECUTOR.shutdown(wait=False, cancel_futures=True)
        try: _SESSION_SHORT.close()
        except: pass
        try: _SESSION_STREAM.close()
        except: pass
        try:
            if _YDL_GLOBAL and hasattr(_YDL_GLOBAL, "close"):
                _YDL_GLOBAL.close()
        except: pass
        print("[lifespan] shutdown: resources closed")
    except Exception as e:
        print(f"[lifespan][shutdown][WARN] {e}")

# Crear la app (único cambio: se pasa lifespan)
app = FastAPI(
    lifespan=lifespan,
    default_response_class=ORJSONResponse  # ← usa orjson para TODAS las respuestas JSON
)

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
""" app.middleware("http")(supa_auth)
print("🔐 Middleware supa_auth registrado") """

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
app.include_router(index.router,     prefix="/api")
app.include_router(music.router,     prefix="/api/music")
app.include_router(playlists.router, prefix="/api/playlists")
app.include_router(feed.router,      prefix="/api/feed")
app.include_router(cache.router,     prefix="/api/cache") 
app.include_router(genres.router,    prefix="/api/genres")
app.include_router(genres.playlists_router, prefix="/api")
app.include_router(upcoming_releases.router, prefix="/api/upcoming-releases")

# Rutas de debug/test (solo en desarrollo)
if ENV != "production":
    app.include_router(debug.router, prefix="/debug")
    app.include_router(debug.router, prefix="/test")