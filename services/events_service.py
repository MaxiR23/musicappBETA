# services/events_service.py
"""
Lógica de negocio para eventos.
Maneja cache y orquestación.
"""
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType
from utils.events_upcoming import fetch_upcoming_events_by_artist

def get_events_by_artist_name(artist_name: str, limit: int = 10, use_cache: bool = True) -> list:
    """Trae eventos de un artista por nombre."""
    if not artist_name or not artist_name.strip():
        return []
    
    cache_key = artist_name.lower().strip()
    
    if use_cache:
        cached = get_cached(CacheType.EVENTS, suffix=cache_key)
        if isinstance(cached, dict) and cached.get("events"):
            return (cached.get("events") or [])[:limit]
    
    try:
        result = fetch_upcoming_events_by_artist(artist_name.strip(), limit=limit, headliner_only=False)

        if not isinstance(result, dict):
            return []

        set_cached(CacheType.EVENTS, result, suffix=cache_key)
        
        # Cache adicional por attractionId
        aid = result.get("attractionId")
        if aid:
            set_cached(CacheType.EVENTS, result, suffix=f"aid:{aid}")
        
        return (result.get("events") or [])[:limit]
    except Exception:
        return []

def get_events_cached_only(artist_name: str, limit: int = 10) -> list:
    """Trae eventos SOLO si están en cache. No hace fetch."""
    if not artist_name or not artist_name.strip():
        return []
    
    cache_key = artist_name.lower().strip()
    cached = get_cached(CacheType.EVENTS, suffix=cache_key)
    
    if isinstance(cached, dict) and cached.get("events"):
        return (cached.get("events") or [])[:limit]
    
    return []

def schedule_events_refresh(artist_name: str):
    """Agenda refresh de eventos en background. No bloquea."""
    if not artist_name or not artist_name.strip():
        return
    
    from services.executor import _EXECUTOR
    
    def _bg():
        try:
            get_events_by_artist_name(artist_name, limit=1, use_cache=False)
        except Exception:
            pass
    
    try:
        _EXECUTOR.submit(_bg)
    except Exception:
        pass