"""
Cache Configuration
-------------------
Configuración centralizada para el sistema de caché.
Define tipos de caché, schedules de invalidación y generación de versiones.
"""

from enum import Enum
from datetime import datetime
from typing import Dict, Optional
import json
from pathlib import Path
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
# PERSISTENCIA DE VERSIONES MANUALES
# ============================================================================

# Path del archivo (en producción será Redis)
_VERSIONS_FILE = Path(__file__).parent.parent / "cache_versions.json"

def _load_manual_versions() -> Dict[str, str]:
    """
    Lee versiones manuales del disco.
    
    MIGRACION A REDIS:
        Cambiar por: return json.loads(redis.get("cache:manual_versions") or "{}")
    """
    if not _VERSIONS_FILE.exists():
        return {}
    try:
        with open(_VERSIONS_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def _save_manual_versions(versions: Dict[str, str]):
    """
    Guarda versiones manuales en disco.
    
    MIGRACION A REDIS:
        Cambiar por: redis.set("cache:manual_versions", json.dumps(versions))
    """
    try:
        with open(_VERSIONS_FILE, 'w') as f:
            json.dump(versions, f, indent=2)
    except Exception as e:
        print(f"Error guardando versiones: {e}")

# ============================================================================
# INVALIDACIÓN MANUAL
# ============================================================================

def set_manual_version(cache_type: CacheType, version: Optional[str] = None):
    """
    Fuerza una versión manual para invalidar el caché inmediatamente.
    Persiste en disco para que funcione entre procesos (script + FastAPI).
    
    Args:
        cache_type: Tipo de caché a invalidar
        version: Versión custom, o None para generar timestamp
    
    Example:
        set_manual_version(CacheType.NEW_RELEASES)
        set_manual_version(CacheType.ARTIST_ALBUMS)
    """
    if version is None:
        version = f"override-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    
    # Cargar, modificar, guardar
    versions = _load_manual_versions()
    versions[cache_type.value] = version
    _save_manual_versions(versions)
    
    print(f"Cache invalidado: {cache_type.value} -> {version}")

def clear_manual_version(cache_type: CacheType):
    """Limpia la versión manual y vuelve al schedule automático"""
    versions = _load_manual_versions()
    if cache_type.value in versions:
        del versions[cache_type.value]
        _save_manual_versions(versions)
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
    # PRIORIDAD 1: Versión manual (lee del disco cada vez)
    manual_versions = _load_manual_versions()
    manual = manual_versions.get(cache_type.value)
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