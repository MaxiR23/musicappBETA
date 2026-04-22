"""
Library view cache: invalidacion de la grilla unificada.

Archivo aparte del library_view_service para evitar imports circulares:
los services de mutacion (playlist, likes, library) importan de aca,
y library_view_service tambien importa de aca. Nadie importa de ellos.
"""
from services.cache_service import invalidate
from services.cache_config import CacheType

_KNOWN_SORTS: tuple[str, ...] = ("recents",)

def invalidate_library_view(user_id: str) -> None:
    """Invalida la grilla unificada en todas las variantes de sort conocidas."""
    for sort in _KNOWN_SORTS:
        invalidate(CacheType.LIBRARY_VIEW, suffix=f"{user_id}:{sort}")