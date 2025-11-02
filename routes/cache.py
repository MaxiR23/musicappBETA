# routes/cache.py
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from services.cache_config import (
    set_manual_version,
    invalidate_related_caches,
    get_all_versions,
    CacheType
)

router = APIRouter(tags=["cache"])

@router.get("/versions")
def get_cache_versions():
    """
    Ver las versiones actuales de todos los cachés.
    
    Example: GET /cache/versions
    """
    return {
        "ok": True,
        "versions": get_all_versions()
    }


@router.post("/invalidate/new-release")
def invalidate_new_release():
    """
    Invalidar cachés cuando sale un álbum nuevo.
    Invalida: NEW_RELEASES, ARTIST_ALBUMS, ARTIST_SINGLES
    
    Example: POST /cache/invalidate/new-release
    """
    invalidate_related_caches(trigger="new_release")
    return {
        "ok": True,
        "message": "Cachés invalidados: NEW_RELEASES, ARTIST_ALBUMS, ARTIST_SINGLES"
    }


@router.post("/invalidate/emergency")
def invalidate_emergency():
    """
    INVALIDAR TODO (emergencia total).
    
    Example: POST /cache/invalidate/emergency
    """
    invalidate_related_caches(trigger="emergency")
    return {
        "ok": True,
        "message": "TODOS los cachés invalidados"
    }


@router.post("/invalidate/{cache_type}")
def invalidate_one(cache_type: str):
    """
    Invalidar UN caché específico.
    
    Example: POST /cache/invalidate/new-releases
    """
    try:
        ct = CacheType(cache_type)
        set_manual_version(ct)
        return {
            "ok": True,
            "message": f"Caché {cache_type} invalidado"
        }
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": f"Tipo de caché inválido: {cache_type}"
            }
        )