# services/cache_service.py
import time

_cache = {}
DEFAULT_TTL = 30 * 60  # 30 minutos

def get_cached(key: str):
    """Devuelve valor cacheado si no expiró"""
    now = time.time()
    if key in _cache:
        entry = _cache[key]
        if now - entry["ts"] < entry.get("ttl", DEFAULT_TTL):
            return entry["data"]
    return None

def set_cached(key: str, data, ttl: int = DEFAULT_TTL):
    """Guarda valor en cache"""
    _cache[key] = {"data": data, "ts": time.time(), "ttl": ttl}

def del_cached(key: str):
    """Elimina una clave del cache"""
    if key in _cache:
        del _cache[key]

def del_many(keys: list[str]):
    """Elimina varias claves del cache"""
    for k in keys:
        _cache.pop(k, None)

def clear_cache():
    """Vacía todo el cache"""
    _cache.clear()