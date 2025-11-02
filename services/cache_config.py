"""
Cache Configuration
-------------------
Configuración centralizada para el sistema de caché.
Define tipos de caché, schedules de invalidación y generación de versiones.
"""

from enum import Enum
from datetime import datetime
from typing import Dict

class CacheType(str, Enum):
    # Feed
    NEW_RELEASES = "new-releases"
    TOP_TRACKS = "top-tracks"
    TOP_ALBUMS = "top-albums"
    SEED_TRACKS = "seed-tracks"
    RECO_ALBUMS = "reco-albums"
    SIMILAR_TO = "similar-to"
    USER_RECOMMENDATIONS = "user-recommendations"
    USER_PLAYLISTS = "user-playlists"
    
    # Music (agregá esto)
    ARTIST = "artist"
    ALBUM = "album"
    ARTIST_ALBUMS = "artist-albums"
    ARTIST_SINGLES = "artist-singles"
    SEARCH = "search"
    EVENTS = "events"
    
    # Genres
    GENRE_PLAYLISTS = "genre-playlists"

    # Upcoming
    UPCOMING_RELEASES = "upcoming-releases"

class CacheSchedule(str, Enum):
    """Schedules de invalidación automática"""
    DAILY = "daily"           # Se rompe cada día a las 00:00
    FRIDAY = "friday"         # Se rompe cada viernes
    SUNDAY = "sunday"         # Se rompe cada domingo
    MANUAL = "manual"         # Solo se invalida manualmente

# ============================================================================
# CONFIGURACIÓN: Define cuándo se invalida cada tipo de caché
# ============================================================================

CACHE_SCHEDULE: Dict[CacheType, CacheSchedule] = {
    CacheType.NEW_RELEASES: CacheSchedule.DAILY,
    CacheType.TOP_TRACKS: CacheSchedule.FRIDAY,
    CacheType.TOP_ALBUMS: CacheSchedule.FRIDAY,
    CacheType.SEED_TRACKS: CacheSchedule.FRIDAY,
    CacheType.RECO_ALBUMS: CacheSchedule.SUNDAY,
    CacheType.SIMILAR_TO: CacheSchedule.SUNDAY,
    CacheType.USER_RECOMMENDATIONS: CacheSchedule.MANUAL,
    CacheType.USER_PLAYLISTS: CacheSchedule.MANUAL,
    
    #music
    CacheType.ARTIST: CacheSchedule.DAILY,  
    CacheType.ALBUM: CacheSchedule.MANUAL,
    CacheType.ARTIST_ALBUMS: CacheSchedule.DAILY, # TODO: invalidar cuando NEW_RELEASES tenga este artista
    CacheType.ARTIST_SINGLES: CacheSchedule.DAILY,    
    CacheType.SEARCH: CacheSchedule.DAILY,   
    CacheType.EVENTS: CacheSchedule.MANUAL,
    
    # Genres
    CacheType.GENRE_PLAYLISTS: CacheSchedule.MANUAL,

    # Upcoming
    CacheType.UPCOMING_RELEASES: CacheSchedule.MANUAL,  # TTL dinámico, no usa schedule
}

# TTL por defecto (en segundos) si no se especifica
DEFAULT_TTL: Dict[CacheType, int] = {
    CacheType.NEW_RELEASES: 86400,          # 24 horas
    CacheType.TOP_TRACKS: 604800,           # 7 días
    CacheType.TOP_ALBUMS: 604800,           # 7 días
    CacheType.SEED_TRACKS: 604800,          # 7 días
    CacheType.RECO_ALBUMS: 604800,          # 7 días
    CacheType.SIMILAR_TO: 604800,           # 7 días
    CacheType.USER_RECOMMENDATIONS: 3600,   # 1 hora
    CacheType.USER_PLAYLISTS: 3600,

    CacheType.ARTIST: 86400,     # 24 horas
    CacheType.ALBUM: 2592000,    # 30 días (nunca cambian)
    CacheType.ARTIST_ALBUMS: 86400,  # 24 horas (por ahora)
    CacheType.ARTIST_SINGLES: 86400, # 24 horas (por ahora)
    CacheType.SEARCH: 3600,      # 1 hora
    CacheType.EVENTS: 86400,     # 24 horas
    
    # Genres
    CacheType.GENRE_PLAYLISTS: 86400,  # 24 horas
    
    # Upcoming 
    CacheType.UPCOMING_RELEASES: 86400,  # Fallback (no se usa porque calculamos smart_ttl)
}

# ============================================================================
# FUNCIONES DE VERSIONADO
# ============================================================================

def get_version(cache_type: CacheType) -> str:
    """
    Genera la versión actual según el schedule del cache_type.
    
    La versión cambia automáticamente cuando se debe invalidar el caché:
    - DAILY: v-20251025 (cambia cada día)
    - FRIDAY: v-2025-w43-FRI (cambia cada viernes)
    - SUNDAY: v-2025-w43-SUN (cambia cada domingo)
    - MANUAL: v-static (nunca cambia automáticamente)
    
    Args:
        cache_type: Tipo de caché
        
    Returns:
        String con la versión actual (ej: "v-20251025", "v-2025-w43-FRI")
    """
    schedule = CACHE_SCHEDULE.get(cache_type, CacheSchedule.MANUAL)
    now = datetime.now()
    
    if schedule == CacheSchedule.DAILY:
        # v-20251025 (año-mes-día)
        return f"v-{now.strftime('%Y%m%d')}"
    
    elif schedule == CacheSchedule.FRIDAY:
        # v-2025-w43-FRI (año-semana-día)
        year, week, _ = now.isocalendar()
        return f"v-{year}-w{week:02d}-FRI"
    
    elif schedule == CacheSchedule.SUNDAY:
        # v-2025-w43-SUN
        year, week, _ = now.isocalendar()
        return f"v-{year}-w{week:02d}-SUN"
    
    else:  # MANUAL
        return "v-static"


def get_all_versions() -> Dict[str, str]:
    """
    Devuelve todas las versiones actuales de todos los tipos de caché.
    Útil para el endpoint /cache/versions
    
    Returns:
        Dict con cache_type -> versión actual
    """
    return {
        cache_type.value: get_version(cache_type)
        for cache_type in CacheType
    }


def get_ttl(cache_type: CacheType) -> int:
    """
    Devuelve el TTL por defecto para un tipo de caché.
    
    Args:
        cache_type: Tipo de caché
        
    Returns:
        TTL en segundos
    """
    return DEFAULT_TTL.get(cache_type, 1800)  # 30 min por defecto