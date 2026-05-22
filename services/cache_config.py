"""
Cache Configuration
-------------------
Configuración centralizada para el sistema de caché.
Define tipos de caché, schedules de invalidación y generación de versiones.
"""

from enum import Enum
from datetime import datetime
from typing import Dict, Optional
import calendar

class CacheType(str, Enum):
    # Feed
    NEW_RELEASES = "new-releases"
    # NEW_SINGLES = "new-singles"  # temporalmente deshabilitado
    TOP_TRACKS = "top-tracks"
    TOP_ALBUMS = "top-albums"
    SEED_TRACKS = "seed-tracks"
    RECO_ALBUMS = "reco-albums"
    SIMILAR_TO = "similar-to"
    USER_RECOMMENDATIONS = "user-recommendations"
    USER_PLAYLISTS = "user-playlists"
    LIKED_TRACKS = "liked-tracks"

    LIBRARY_VIEW = "library-view"
    
    # Music
    ARTIST = "artist"
    ALBUM = "album"
    ARTIST_ALBUMS = "artist-albums"
    ARTIST_SINGLES = "artist-singles"
    PRESENTING = "presenting"
    SEARCH = "search"
    EVENTS = "events"
    
    # Genres
    GENRE_PLAYLISTS = "genre-playlists"

    # Upcoming
    UPCOMING_RELEASES = "upcoming-releases"
    UPCOMING_ARTIST = "upcoming-artist"

    # Repeat
    REPLAY = "replay"
    LISTEN_AGAIN = "listen-again"
    USER_STATIONS = "user-stations"

    # Featured
    FEATURED_NEW_RELEASE = "featured-new-release"
    RECOMMENDED_PLAYLISTS = "recommended-playlists"

    # Stats
    WEEKLY_STATS = "weekly-stats"
    MONTHLY_STATS = "monthly-stats"

class CacheSchedule(str, Enum):
    """Schedules de invalidación automática"""
    TWICE_WEEKLY = "twice-weekly"
    DAILY = "daily"
    MONDAY = "monday"
    TUESDAY = "tuesday"
    FRIDAY = "friday"
    SUNDAY = "sunday"
    MANUAL = "manual"

# ============================================================================
# CONFIGURACIÓN: Define cuándo se invalida cada tipo de caché
# ============================================================================

CACHE_SCHEDULE: Dict[CacheType, CacheSchedule] = {
    CacheType.NEW_RELEASES: CacheSchedule.MANUAL,
    # CacheType.NEW_SINGLES: CacheSchedule.TWICE_WEEKLY, # temporalmente deshabilitado
    CacheType.TOP_TRACKS: CacheSchedule.SUNDAY,
    CacheType.TOP_ALBUMS: CacheSchedule.SUNDAY,
    CacheType.SEED_TRACKS: CacheSchedule.FRIDAY,
    CacheType.RECO_ALBUMS: CacheSchedule.SUNDAY,
    CacheType.SIMILAR_TO: CacheSchedule.SUNDAY,
    CacheType.USER_RECOMMENDATIONS: CacheSchedule.MONDAY,
    CacheType.USER_PLAYLISTS: CacheSchedule.MANUAL,
    CacheType.LIKED_TRACKS: CacheSchedule.MANUAL,

    CacheType.LIBRARY_VIEW: CacheSchedule.MANUAL,
    
    CacheType.ARTIST: CacheSchedule.DAILY,  
    CacheType.ALBUM: CacheSchedule.MANUAL,
    CacheType.ARTIST_ALBUMS: CacheSchedule.TWICE_WEEKLY,
    CacheType.ARTIST_SINGLES: CacheSchedule.TWICE_WEEKLY,
    CacheType.PRESENTING: CacheSchedule.DAILY,
    CacheType.SEARCH: CacheSchedule.DAILY,   
    CacheType.EVENTS: CacheSchedule.MANUAL,
    
    CacheType.GENRE_PLAYLISTS: CacheSchedule.MANUAL,

    CacheType.UPCOMING_RELEASES: CacheSchedule.MANUAL,
    CacheType.UPCOMING_ARTIST: CacheSchedule.MANUAL,

    CacheType.REPLAY: CacheSchedule.FRIDAY,
    CacheType.LISTEN_AGAIN: CacheSchedule.FRIDAY,
    CacheType.USER_STATIONS: CacheSchedule.TUESDAY,

    CacheType.FEATURED_NEW_RELEASE: CacheSchedule.SUNDAY,
    CacheType.RECOMMENDED_PLAYLISTS: CacheSchedule.MONDAY,

    CacheType.WEEKLY_STATS: CacheSchedule.MONDAY,
    CacheType.MONTHLY_STATS: CacheSchedule.MANUAL,
}

DEFAULT_TTL: Dict[CacheType, int] = {
    CacheType.NEW_RELEASES: 86400,
    # CacheType.NEW_SINGLES: 86400,  # temporalmente deshabilitado
    CacheType.TOP_TRACKS: 604800,
    CacheType.TOP_ALBUMS: 604800,
    CacheType.SEED_TRACKS: 604800,
    CacheType.RECO_ALBUMS: 604800,
    CacheType.SIMILAR_TO: 604800,
    CacheType.USER_RECOMMENDATIONS: 604800,
    CacheType.USER_PLAYLISTS: 3600,
    CacheType.LIKED_TRACKS: 3600,

    CacheType.LIBRARY_VIEW: 3600,

    CacheType.ARTIST: 86400,
    CacheType.ALBUM: 2592000,
    CacheType.ARTIST_ALBUMS: 86400,
    CacheType.ARTIST_SINGLES: 86400,
    CacheType.PRESENTING: 86400,
    CacheType.SEARCH: 3600,
    CacheType.EVENTS: 86400,
    
    CacheType.GENRE_PLAYLISTS: 86400,
    
    CacheType.UPCOMING_RELEASES: 86400,
    CacheType.UPCOMING_ARTIST: 86400,

    CacheType.REPLAY: 604800,
    CacheType.LISTEN_AGAIN: 604800,
    CacheType.USER_STATIONS: 604800,

    CacheType.FEATURED_NEW_RELEASE: 604800,
    CacheType.RECOMMENDED_PLAYLISTS: 604800,

    CacheType.WEEKLY_STATS: 604800,
}

# ============================================================================
# PERSISTENCIA DE VERSIONES MANUALES (Redis)
# ============================================================================
from .redis_client import get_redis

# Namespace para las keys de versiones manuales en Redis
_MANUAL_VERSION_PREFIX = "cache:manual:"


def _manual_version_key(cache_type_value: str) -> str:
    """Construye la key de Redis para un cache_type dado."""
    return f"{_MANUAL_VERSION_PREFIX}{cache_type_value}"


def _get_manual_version(cache_type_value: str) -> Optional[str]:
    """Lee la version manual de Redis. None si no existe."""
    try:
        return get_redis().get(_manual_version_key(cache_type_value))
    except Exception as e:
        print(f"Error leyendo version manual de Redis ({cache_type_value}): {e}")
        return None


def _set_manual_version(cache_type_value: str, version: str):
    """Guarda la version manual en Redis."""
    try:
        get_redis().set(_manual_version_key(cache_type_value), version)
    except Exception as e:
        print(f"Error guardando version manual en Redis ({cache_type_value}): {e}")


def _delete_manual_version(cache_type_value: str):
    """Borra la version manual de Redis."""
    try:
        get_redis().delete(_manual_version_key(cache_type_value))
    except Exception as e:
        print(f"Error borrando version manual de Redis ({cache_type_value}): {e}")
# ============================================================================
# INVALIDACIÓN MANUAL
# ============================================================================

def set_manual_version(cache_type: CacheType, version: Optional[str] = None):
    """
    Fuerza una version manual para invalidar el cache inmediatamente.
    Persiste en Redis para que funcione entre procesos (script + FastAPI).
    
    Args:
        cache_type: Tipo de cache a invalidar
        version: Version custom, o None para generar timestamp
    
    Example:
        set_manual_version(CacheType.NEW_RELEASES)
        set_manual_version(CacheType.ARTIST_ALBUMS)
    """
    if version is None:
        version = f"override-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    
    _set_manual_version(cache_type.value, version)
    print(f"Cache invalidado: {cache_type.value} -> {version}")


def clear_manual_version(cache_type: CacheType):
    """Limpia la version manual y vuelve al schedule automatico"""
    _delete_manual_version(cache_type.value)
    print(f"Cache restaurado: {cache_type.value}")

def invalidate_related_caches(trigger: str = "new_release"):
    """
    Invalida múltiples cachés relacionados de una vez.
    
    Args:
        trigger: Razón de la invalidación
            - "new_release": Álbum nuevo salió
            - "emergency": Invalidación total
    
    Example:
        invalidate_related_caches(trigger="new_release")
    """
    if trigger == "new_release":
        set_manual_version(CacheType.NEW_RELEASES)
        set_manual_version(CacheType.ARTIST_ALBUMS)
        # set_manual_version(CacheType.ARTIST_SINGLES) tempormalmente deshabilitado
        print(f"Caches invalidados por: {trigger}")
    
    elif trigger == "emergency":
        for cache_type in CacheType:
            set_manual_version(cache_type)
        print("EMERGENCIA: Todos los caches invalidados")

# ============================================================================
# FUNCIONES DE VERSIONADO
# ============================================================================

def get_version(cache_type: CacheType) -> str:
    """
    Genera la versión actual según el schedule del cache_type.
    
    PRIORIDAD:
    1. Versión manual (del archivo JSON / Redis)
    2. Versión automática (según schedule)
    
    Returns:
        String con la versión actual (ej: "v-20251025", "override-20241106-234625")
    """
    # PRIORIDAD 1: Version manual (lee de Redis)
    manual = _get_manual_version(cache_type.value)
    if manual:
        return manual
    
    # PRIORIDAD 2: Versión automática
    schedule = CACHE_SCHEDULE.get(cache_type, CacheSchedule.MANUAL)
    now = datetime.now()
    
    if schedule == CacheSchedule.DAILY:
        return f"v-{now.strftime('%Y%m%d')}"
    
    elif schedule == CacheSchedule.TWICE_WEEKLY:
        year, week, dow = now.isocalendar()
        day_names = {0: "DOM", 1: "LUN", 2: "MAR", 3: "MIE", 4: "JUE", 5: "VIE", 6: "SAB"}
        
        if dow == 7:
            dow_key = 0
        elif dow in [1, 3, 5]:
            dow_key = dow
        else:
            if dow == 2:
                dow_key = 1
            elif dow == 4:
                dow_key = 3
            elif dow == 6:
                dow_key = 5
            else:
                dow_key = dow
        
        return f"v-{year}-w{week:02d}-{day_names[dow_key]}"
    
    elif schedule == CacheSchedule.MONDAY:
        year, week, _ = now.isocalendar()
        return f"v-{year}-w{week:02d}-MON"
    
    elif schedule == CacheSchedule.TUESDAY:
        year, week, _ = now.isocalendar()
        return f"v-{year}-w{week:02d}-TUE"
    
    elif schedule == CacheSchedule.FRIDAY:
        year, week, _ = now.isocalendar()
        return f"v-{year}-w{week:02d}-FRI"
    
    elif schedule == CacheSchedule.SUNDAY:
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

    if cache_type == CacheType.MONTHLY_STATS:
        today = datetime.now()
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        return days_in_month * 86400

    return DEFAULT_TTL.get(cache_type, 1800)