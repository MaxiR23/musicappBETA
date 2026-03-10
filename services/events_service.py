"""
Lógica de negocio para eventos.
Maneja cache y orquestación.
"""
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType
from utils.events_upcoming import fetch_upcoming_events_by_artist

def normalize_artist_name(artist_name: str | None) -> str | None:
    """Normaliza nombre de artista para cache key. Retorna None si inválido."""
    if not artist_name or not artist_name.strip():
        return None
    return artist_name.lower().strip()

def extract_events_from_cache(cached: dict | None, limit: int) -> list:
    """Extrae lista de eventos de un resultado cacheado."""
    if not isinstance(cached, dict):
        return []
    events = cached.get("events") or []
    return events[:limit]

def extract_events_from_result(result: dict | None, limit: int) -> list:
    """Extrae lista de eventos de un resultado de fetch."""
    if not isinstance(result, dict):
        return []
    return (result.get("events") or [])[:limit]

# ── IO ───────────────────────────────────────────────────
def get_events_by_artist_name(artist_name: str, limit: int = 10, use_cache: bool = True) -> list:
    """Trae eventos de un artista por nombre."""
    cache_key = normalize_artist_name(artist_name)
    if not cache_key:
        return []

    if use_cache:
        cached = get_cached(CacheType.EVENTS, suffix=cache_key)
        events = extract_events_from_cache(cached, limit)
        if events:
            return events

    try:
        result = fetch_upcoming_events_by_artist(artist_name.strip(), limit=limit, headliner_only=False)
        if not isinstance(result, dict):
            return []

        set_cached(CacheType.EVENTS, result, suffix=cache_key)

        aid = result.get("attractionId")
        if aid:
            set_cached(CacheType.EVENTS, result, suffix=f"aid:{aid}")

        return extract_events_from_result(result, limit)
    except Exception:
        return []

def get_events_cached_only(artist_name: str, limit: int = 10) -> list:
    """Trae eventos SOLO si están en cache. No hace fetch."""
    cache_key = normalize_artist_name(artist_name)
    if not cache_key:
        return []

    cached = get_cached(CacheType.EVENTS, suffix=cache_key)
    return extract_events_from_cache(cached, limit)

def schedule_events_refresh(artist_name: str) -> None:
    """Agenda refresh de eventos en background. No bloquea."""
    if not normalize_artist_name(artist_name):
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