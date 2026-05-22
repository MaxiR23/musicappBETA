"""
Cache Service
-------------
Sistema de caché en memoria con versionado automático.
Preparado para migrar a Redis en el futuro sin cambiar el código que lo usa.

Migración a Redis:
    1. pip install redis
    2. Descomentar la sección REDIS
    3. Comentar la sección IN-MEMORY
    4. Listo! El resto del código sigue funcionando igual.
"""

import time
import json
from functools import wraps
from typing import Optional, Callable, Any, TypeVar, ParamSpec
from .cache_config import CacheType, get_version, get_ttl

# ============================================================================
# STORAGE BACKEND - Cambia entre IN-MEMORY y REDIS sin tocar el resto
# ============================================================================

# === OPCIÓN 1: IN-MEMORY (desarrollo local) ===
_cache: dict = {}

def _get(key: str) -> Optional[str]:
    """Lee del storage (memoria)"""
    return _cache.get(key)

def _set(key: str, value: str, ttl: Optional[int] = None):
    """Escribe al storage (memoria)"""
    _cache[key] = value

def _delete(key: str):
    """Elimina del storage (memoria)"""
    _cache.pop(key, None)

def _clear():
    """Limpia todo el storage (memoria)"""
    _cache.clear()

def _keys_pattern(pattern: str) -> list[str]:
    """Busca keys que matcheen el pattern (memoria)"""
    if pattern.endswith("*"):
        prefix = pattern[:-1]
        return [k for k in _cache.keys() if k.startswith(prefix)]
    return [k for k in _cache.keys() if k == pattern]


# === OPCIÓN 2: REDIS (producción) ===
# Descomentar cuando migres a Kamatera:
"""
import redis

_redis = redis.Redis(
    host='localhost',  # o tu IP de Redis
    port=6379,
    decode_responses=True,
    db=0
)

def _get(key: str) -> Optional[str]:
    return _redis.get(key)

def _set(key: str, value: str, ttl: Optional[int] = None):
    if ttl:
        _redis.setex(key, ttl, value)
    else:
        _redis.set(key, value)

def _delete(key: str):
    _redis.delete(key)

def _clear():
    _redis.flushdb()

def _keys_pattern(pattern: str) -> list[str]:
    return [k.decode() if isinstance(k, bytes) else k for k in _redis.keys(pattern)]
"""
# ============================================================================
# CACHE FUNCTIONS - NO tocar cuando migres a Redis
# ============================================================================

def _make_key(
    cache_type: CacheType,
    suffix: str = "",
    *,
    entity_id: Optional[str] = None,
) -> str:
    """
    Genera la key del cache con version automatica.

    Resolucion de version:
      1. Si se pasa entity_id explicito y el cache_type es per-entity, se usa
         para resolver la version per-entity.
      2. Si no se pasa entity_id pero hay suffix y el cache_type es per-entity,
         el suffix actua como entity_id (fallback).
      3. Si no, version global/schedule.

    El cache key siempre se arma con el suffix (independiente de entity_id),
    asi se mantiene el aislamiento por user/contexto cuando es necesario.
    """
    from .cache_config import PER_ENTITY_CACHE_TYPES

    if entity_id is None and suffix and cache_type in PER_ENTITY_CACHE_TYPES:
        entity_id = suffix

    if entity_id is not None and cache_type not in PER_ENTITY_CACHE_TYPES:
        entity_id = None  # cache_type no soporta per-entity, ignorar

    version = get_version(cache_type, entity_id=entity_id)
    base = f"{cache_type.value}:{version}"
    return f"{base}:{suffix}" if suffix else base


def get_cached(
    cache_type: CacheType,
    suffix: str = "",
    *,
    entity_id: Optional[str] = None,
) -> Optional[Any]:
    """Lee del cache. Ver _make_key para semantica de entity_id."""
    key = _make_key(cache_type, suffix, entity_id=entity_id)
    raw = _get(key)

    if raw is None:
        return None

    try:
        entry = json.loads(raw)
        now = time.time()
        if now - entry["ts"] < entry.get("ttl", get_ttl(cache_type)):
            return entry["data"]
        _delete(key)
        return None
    except (json.JSONDecodeError, KeyError):
        _delete(key)
        return None


def set_cached(
    cache_type: CacheType,
    data: Any,
    suffix: str = "",
    ttl: Optional[int] = None,
    *,
    entity_id: Optional[str] = None,
):
    """Guarda en cache. Ver _make_key para semantica de entity_id."""
    key = _make_key(cache_type, suffix, entity_id=entity_id)

    entry = {
        "data": data,
        "ts": time.time(),
        "ttl": ttl or get_ttl(cache_type)
    }

    _set(key, json.dumps(entry), ttl=entry["ttl"])

# ============================================================================
# DECORATOR - Para aplicar caché de forma declarativa
# ============================================================================

P = ParamSpec('P')
T = TypeVar('T')

def cached(
    cache_type: CacheType,
    ttl: Optional[int] = None,
    key_builder: Optional[Callable[..., str]] = None
):
    """
    Decorator para cachear automáticamente funciones/endpoints.
    
    Args:
        cache_type: Tipo de caché
        ttl: TTL en segundos (opcional)
        key_builder: Función para construir suffix de la key desde los args (opcional)
        
    Example:
        # Caché simple
        @cached(CacheType.NEW_RELEASES)
        async def get_new_releases():
            return fetch_from_db()
        
        # Caché por usuario
        @cached(CacheType.USER_RECOMMENDATIONS, key_builder=lambda user_id: user_id)
        async def get_user_reco(user_id: str):
            return fetch_user_data(user_id)
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Construye suffix si hay key_builder
            suffix = ""
            if key_builder:
                try:
                    suffix = key_builder(*args, **kwargs)
                except Exception:
                    pass  # Si falla, usa key sin suffix
            
            # Intenta leer del caché
            cached_data = get_cached(cache_type, suffix)
            if cached_data is not None:
                print(f"[CACHE HIT] {cache_type.value}:{suffix or '(no-suffix)'}")
                return cached_data
            
            # Cache miss - ejecuta función
            print(f"[CACHE MISS] {cache_type.value}:{suffix or '(no-suffix)'}")
            result = await func(*args, **kwargs)
            
            # Guarda en caché
            set_cached(cache_type, result, suffix, ttl)
            return result
        
        return wrapper
    return decorator

# ============================================================================
# INVALIDACIÓN - Para borrar caché manualmente
# ============================================================================
def invalidate(
    cache_type: CacheType,
    suffix: str = "",
    *,
    entity_id: Optional[str] = None,
):
    """Invalida una key especifica del cache."""
    key = _make_key(cache_type, suffix, entity_id=entity_id)
    _delete(key)

def invalidate_all(cache_type: CacheType):
    """
    Invalida TODAS las keys de un tipo (útil para caché con suffix).
    
    Example:
        # Borra todos los USER_RECOMMENDATIONS de todos los usuarios
        invalidate_all(CacheType.USER_RECOMMENDATIONS)
    """
    pattern = f"{cache_type.value}:*"
    keys = _keys_pattern(pattern)
    for key in keys:
        _delete(key)
    print(f"[CACHE INVALIDATED ALL] {cache_type.value} ({len(keys)} keys)")

def clear_all_cache():
    """Limpia TODO el caché. Usar con cuidado."""
    _clear()
    print("[CACHE CLEARED] Todo el caché fue eliminado")

# ============================================================================
# COMPATIBILIDAD - Mantiene tus funciones viejas funcionando
# ============================================================================

DEFAULT_TTL = 30 * 60  # 30 minutos
_legacy_cache: dict = {}

def get_cached_legacy(key: str) -> Optional[Any]:
    """Legacy: para endpoints que usan strings (lyrics, related, upnext)"""
    entry = _legacy_cache.get(key)
    if not entry:
        return None
    
    if time.time() - entry["ts"] > entry["ttl"]:
        _legacy_cache.pop(key, None)
        return None
    
    return entry["data"]

def set_cached_legacy(key: str, data: Any, ttl: int = 1800):
    """Legacy: para endpoints que usan strings"""
    _legacy_cache[key] = {"data": data, "ts": time.time(), "ttl": ttl}

def del_cached(key: str):
    """Legacy: elimina una key sin versionado"""
    _delete(key)

def del_many(keys: list[str]):
    """Legacy: elimina varias keys sin versionado"""
    for k in keys:
        _delete(k)

def clear_cache():
    """Legacy: limpia todo"""
    clear_all_cache()