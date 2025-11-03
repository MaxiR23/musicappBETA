"""
Cache Configuration
-------------------
Configuración centralizada para el sistema de caché.
Define tipos de caché, schedules de invalidación y generación de versiones.
"""

from enum import Enum
from datetime import datetime
from typing import Dict, Optional

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
    
    # Music
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
    UPCOMING_ARTIST = "upcoming-artist" # Tipo de caché por artista individual.

class CacheSchedule(str, Enum):
    """Schedules de invalidación automática"""
    TWICE_WEEKLY = "twice-weekly"  # Se rompe Lun, Mié, Vie, Dom (sincronizado con cron de new_releases)
    DAILY = "daily"                # Se rompe cada día a las 00:00
    MONDAY = "monday"              # Se rompe cada lunes
    FRIDAY = "friday"              # Se rompe cada viernes
    SUNDAY = "sunday"              # Se rompe cada domingo
    MANUAL = "manual"              # Solo se invalida manualmente

# ============================================================================
# CONFIGURACIÓN: Define cuándo se invalida cada tipo de caché
# ============================================================================

CACHE_SCHEDULE: Dict[CacheType, CacheSchedule] = {
    CacheType.NEW_RELEASES: CacheSchedule.TWICE_WEEKLY,  # Lun/Mié/Vie/Dom 2am
    CacheType.TOP_TRACKS: CacheSchedule.SUNDAY,          # Domingos 2am
    CacheType.TOP_ALBUMS: CacheSchedule.SUNDAY,          # Domingos 2am
    CacheType.SEED_TRACKS: CacheSchedule.FRIDAY,         # Viernes 2am
    CacheType.RECO_ALBUMS: CacheSchedule.SUNDAY,
    CacheType.SIMILAR_TO: CacheSchedule.SUNDAY,
    CacheType.USER_RECOMMENDATIONS: CacheSchedule.MONDAY,
    CacheType.USER_PLAYLISTS: CacheSchedule.MANUAL,
    
    # Music
    CacheType.ARTIST: CacheSchedule.DAILY,  
    CacheType.ALBUM: CacheSchedule.MANUAL,
    CacheType.ARTIST_ALBUMS: CacheSchedule.TWICE_WEEKLY,  # Se invalida junto con NEW_RELEASES
    CacheType.ARTIST_SINGLES: CacheSchedule.TWICE_WEEKLY, # Se invalida junto con NEW_RELEASES
    CacheType.SEARCH: CacheSchedule.DAILY,   
    CacheType.EVENTS: CacheSchedule.MANUAL,
    
    # Genres
    CacheType.GENRE_PLAYLISTS: CacheSchedule.MANUAL,

    # Upcoming
    CacheType.UPCOMING_RELEASES: CacheSchedule.MANUAL,  # TTL dinámico, no usa schedule
    CacheType.UPCOMING_ARTIST: CacheSchedule.MANUAL,  # TTL dinámico, cache releases por ARTISTA.
}

# TTL por defecto (en segundos) si no se especifica
DEFAULT_TTL: Dict[CacheType, int] = {
    CacheType.NEW_RELEASES: 86400,          # 24 horas
    CacheType.TOP_TRACKS: 604800,           # 7 días
    CacheType.TOP_ALBUMS: 604800,           # 7 días
    CacheType.SEED_TRACKS: 604800,          # 7 días
    CacheType.RECO_ALBUMS: 604800,          # 7 días
    CacheType.SIMILAR_TO: 604800,           # 7 días
    CacheType.USER_RECOMMENDATIONS: 604800, # 7 días
    CacheType.USER_PLAYLISTS: 3600,

    CacheType.ARTIST: 86400,     # 24 horas
    CacheType.ALBUM: 2592000,    # 30 días (nunca cambian)
    CacheType.ARTIST_ALBUMS: 86400,  # 24 horas
    CacheType.ARTIST_SINGLES: 86400, # 24 horas
    CacheType.SEARCH: 3600,      # 1 hora
    CacheType.EVENTS: 86400,     # 24 horas
    
    # Genres
    CacheType.GENRE_PLAYLISTS: 86400,  # 24 horas
    
    # Upcoming 
    CacheType.UPCOMING_RELEASES: 86400,  # Fallback (no se usa porque calculamos smart_ttl)
    CacheType.UPCOMING_ARTIST: 86400,    # Fallback (rara vez se usa)
}

# ============================================================================
# INVALIDACIÓN MANUAL (Para emergencias)
# ============================================================================

# Variable global para versiones forzadas
_MANUAL_VERSIONS: Dict[CacheType, Optional[str]] = {}

def set_manual_version(cache_type: CacheType, version: Optional[str] = None):
    """
    Fuerza una versión manual para invalidar el caché inmediatamente.
    
    Args:
        cache_type: Tipo de caché a invalidar
        version: Versión custom, o None para generar timestamp
    
    Example:
        # Bad Bunny sacó álbum el miércoles
        set_manual_version(CacheType.NEW_RELEASES)
        set_manual_version(CacheType.ARTIST_ALBUMS)
    """
    if version is None:
        version = f"override-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    _MANUAL_VERSIONS[cache_type] = version
    print(f"Cache invalidado: {cache_type.value} -> {version}")

def clear_manual_version(cache_type: CacheType):
    """Limpia la versión manual y vuelve al schedule automático"""
    if cache_type in _MANUAL_VERSIONS:
        del _MANUAL_VERSIONS[cache_type]
        print(f"Cache restaurado: {cache_type.value}")

def invalidate_related_caches(trigger: str = "new_release"):
    """
    Invalida múltiples cachés relacionados de una vez.
    
    Args:
        trigger: Razón de la invalidación
            - "new_release": Álbum nuevo salió
            - "emergency": Invalidación total
    
    Example:
        # Álbum nuevo salió hoy
        invalidate_related_caches(trigger="new_release")
    """
    if trigger == "new_release":
        set_manual_version(CacheType.NEW_RELEASES)
        set_manual_version(CacheType.ARTIST_ALBUMS)
        set_manual_version(CacheType.ARTIST_SINGLES)
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
    
    La versión cambia automáticamente cuando se debe invalidar el caché:
    - TWICE_WEEKLY: v-2025-w44-LUN/MIE/VIE/DOM (cambia lun, mié, vie, dom)
    - DAILY: v-20251025 (cambia cada día)
    - MONDAY: v-2025-w43-MON (cambia cada lunes)
    - FRIDAY: v-2025-w43-FRI (cambia cada viernes)
    - SUNDAY: v-2025-w43-SUN (cambia cada domingo)
    - MANUAL: v-static (nunca cambia automáticamente)
    
    Args:
        cache_type: Tipo de caché
        
    Returns:
        String con la versión actual (ej: "v-20251025", "v-2025-w43-FRI")
    """
    # PRIORIDAD 1: Si hay versión manual, usar esa
    manual = _MANUAL_VERSIONS.get(cache_type)
    if manual:
        return manual
    
    # PRIORIDAD 2: Generar según schedule automático
    schedule = CACHE_SCHEDULE.get(cache_type, CacheSchedule.MANUAL)
    now = datetime.now()
    
    if schedule == CacheSchedule.DAILY:
        # v-20251025 (año-mes-día)
        return f"v-{now.strftime('%Y%m%d')}"
    
    elif schedule == CacheSchedule.TWICE_WEEKLY:
        # v-2025-w44-LUN/MIE/VIE/DOM
        year, week, dow = now.isocalendar()
        day_names = {0: "DOM", 1: "LUN", 2: "MAR", 3: "MIE", 4: "JUE", 5: "VIE", 6: "SAB"}
        
        # Mapear a los días que actualizan (lun=1, mié=3, vie=5, dom=7)
        if dow == 7:  # Domingo
            dow_key = 0
        elif dow in [1, 3, 5]:  # Lun, Mié, Vie
            dow_key = dow
        else:  # Otros días: mantener última versión
            if dow == 2:  # Martes -> versión del Lunes
                dow_key = 1
            elif dow == 4:  # Jueves -> versión del Miércoles
                dow_key = 3
            elif dow == 6:  # Sábado -> versión del Viernes
                dow_key = 5
            else:
                dow_key = dow
        
        return f"v-{year}-w{week:02d}-{day_names[dow_key]}"
    
    elif schedule == CacheSchedule.MONDAY:
        # v-2025-w43-MON
        year, week, _ = now.isocalendar()
        return f"v-{year}-w{week:02d}-MON"
    
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