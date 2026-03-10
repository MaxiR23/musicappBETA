# services/upcoming_releases_repo.py (VERSIÓN OPTIMIZADA)
from __future__ import annotations
from typing import Any, Dict, List, Optional, Set, Tuple
from datetime import date, datetime

from services.supabase_service import supabase_service as sb
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType

TABLE = "upcoming_releases"
FEED_TABLE = "feed_current"

def _get_feed_releases_set() -> Set[Tuple[str, str]]:
    """
    Obtiene TODOS los releases en feed_current como un set de tuplas (artist, album).
    Esto permite hacer una sola query y luego filtrar en memoria.
    """
    try:
        res = sb.table(FEED_TABLE).select("artist, album, title").execute()
        rows = getattr(res, "data", None) or []
    except Exception as e:
        print(f"[upcoming_repo][_get_feed_releases_set][ERROR] {e}")
        return set()
    
    feed_set = set()
    for row in rows:
        artist = (row.get("artist") or "").lower().strip()
        # Intentar con album primero, luego title
        album = (row.get("album") or row.get("title") or "").lower().strip()
        if artist and album:
            feed_set.add((artist, album))
    
    return feed_set

def _filter_releases_not_in_feed(releases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filtra los releases que ya están en feed_current.
    Hace UNA sola query al feed y luego filtra en memoria.
    """
    if not releases:
        return []
    
    # Una sola query para obtener todo el feed
    feed_set = _get_feed_releases_set()
    
    if not feed_set:
        return releases  # Si no hay feed, devolvemos todo
    
    # Filtrar en memoria
    filtered = []
    for release in releases:
        artist_name = (release.get("artist_name") or "").lower().strip()
        album_name = (release.get("album_name") or "").lower().strip()
        
        # Si NO está en el feed, lo incluimos
        if artist_name and album_name:
            if (artist_name, album_name) not in feed_set:
                filtered.append(release)
        else:
            # Si falta info, lo incluimos por seguridad
            filtered.append(release)
    
    return filtered

def list_upcoming_releases(
    include_tba: bool = True,
    limit: int = 50,
    filter_feed: bool = True
) -> List[Dict[str, Any]]:
    """
    Trae releases futuros (desde hoy en adelante).
    Si include_tba=True, también trae los TBA.
    Si filter_feed=True, excluye los que ya están en feed_current.
    """
    today = date.today().isoformat()
    
    # Traemos más de lo necesario porque algunos se filtrarán
    fetch_limit = limit * 2 if filter_feed else limit
    
    try:
        q = sb.table(TABLE).select("*")
        if include_tba:
            q = q.or_(f"release_date.gte.{today},is_tba.eq.true")
        else:
            q = q.gte("release_date", today)
        q = q.order("is_tba", desc=False).order("release_date", desc=False).limit(fetch_limit)
        res = q.execute()
        releases = getattr(res, "data", None) or []
    except Exception as e:
        print(f"[upcoming_repo][list_upcoming_releases][ERROR] {e}")
        return []
    
    # Filtrar los que ya están en feed_current (1 sola query)
    if filter_feed and releases:
        releases = _filter_releases_not_in_feed(releases)
    
    # Limitar al número solicitado
    return releases[:limit]

def count_upcoming_releases(filter_feed: bool = True) -> int:
    """
    Cuenta cuántos releases hay en total (para stats).
    Si filter_feed=True, excluye los que ya están en feed_current.
    """
    today = date.today().isoformat()
    try:
        res = (
            sb.table(TABLE)
            .select("*")
            .or_(f"release_date.gte.{today},is_tba.eq.true")
            .execute()
        )
        releases = getattr(res, "data", None) or []
    except Exception as e:
        print(f"[upcoming_repo][count_upcoming_releases][ERROR] {e}")
        return 0
    
    if filter_feed and releases:
        releases = _filter_releases_not_in_feed(releases)
    
    return len(releases)

def get_next_release_date(filter_feed: bool = True) -> date | None:
    """
    Encuentra la fecha del próximo release (>=hoy) que NO esté en feed.
    Devuelve None si no hay más releases.
    """
    today = date.today()
    try:
        res = (
            sb.table(TABLE)
            .select("*")
            .gte("release_date", today.isoformat())
            .order("release_date", desc=False)
            .limit(20)  # Traemos varios por si algunos están en feed
            .execute()
        )
        rows = getattr(res, "data", []) or []
    except Exception as e:
        print(f"[upcoming_repo][get_next_release_date][ERROR] {e}")
        return None
    
    if not rows:
        return None
    
    # Filtrar si es necesario
    if filter_feed:
        rows = _filter_releases_not_in_feed(rows)
    
    if not rows:
        return None
    
    release_str = rows[0].get("release_date")
    if not release_str:
        return None
    return datetime.fromisoformat(release_str).date()

def calculate_smart_ttl(filter_feed: bool = True) -> int:
    """
    Calcula TTL inteligente:
    - Si hay próximo release: TTL = días hasta ese release + 2 horas
    - Si NO hay: TTL = 7 días (default)
    """
    next_release = get_next_release_date(filter_feed)
    if not next_release:
        return 7 * 86400
    today = date.today()
    days_until = (next_release - today).days
    if days_until <= 0:
        return 2 * 3600
    return (days_until * 86400) + (2 * 3600)

def list_upcoming_releases_cached(
    include_tba: bool = True,
    limit: int = 50,
    filter_feed: bool = True
) -> List[Dict[str, Any]]:
    """
    Versión cacheada con TTL inteligente.
    El caché expira solo cuando hay un nuevo release.
    """
    cache_key = f"tba={include_tba}:limit={limit}:feed={filter_feed}"
    cached = get_cached(CacheType.UPCOMING_RELEASES, suffix=cache_key)
    if cached is not None:
        return cached
    releases = list_upcoming_releases(include_tba, limit, filter_feed)
    smart_ttl = calculate_smart_ttl(filter_feed)
    set_cached(CacheType.UPCOMING_RELEASES, releases, suffix=cache_key, ttl=smart_ttl)
    return releases

def get_upcoming_by_artist_id(artist_id: str, filter_feed: bool = True) -> Optional[Dict[str, Any]]:
    """
    Devuelve el PRÓXIMO lanzamiento confirmado (no-TBA) para un artista dado su `artist_id`.
    Si filter_feed=True, excluye los que ya están en feed_current.
    """
    today = date.today().isoformat()
    try:
        q = (
            sb.table(TABLE)
            .select("release_date, artist_name, album_name, label, thumbnail_url, track_count, artist_id")
            .eq("artist_id", artist_id)
            .gte("release_date", today)
            .or_("is_tba.is.false,is_tba.is.null")
            .order("release_date", desc=False)
            .limit(10)  # Traemos más por si hay algunos en feed
        )
        res = q.execute()
        rows = getattr(res, "data", None) or []
    except Exception as e:
        print(f"[upcoming_repo][get_upcoming_by_artist_id][ERROR] {e}")
        return None
    
    if not rows:
        return None
    
    # Filtrar los que ya están en feed_current (1 sola query)
    if filter_feed:
        rows = _filter_releases_not_in_feed(rows)
        if not rows:
            return None
    
    r = rows[0]
    
    return {
        "release_date": r.get("release_date"),
        "artist": r.get("artist_name"),
        "album": r.get("album_name"),
        "label": r.get("label"),
        "thumbnail": r.get("thumbnail_url"),
        "track_count": r.get("track_count"),
        "artist_id": r.get("artist_id"),
    }

def get_upcoming_by_artist_id_cached(artist_id: str, filter_feed: bool = True) -> Optional[Dict[str, Any]]:
    """
    Versión cacheada con TTL inteligente.
    El caché expira automáticamente el día del release.
    """
    cache_key = f"{artist_id}:feed={filter_feed}"
    cached = get_cached(CacheType.UPCOMING_ARTIST, suffix=cache_key)
    if cached is not None:
        return cached
    upcoming = get_upcoming_by_artist_id(artist_id, filter_feed)
    if not upcoming:
        ttl = 7 * 86400
    else:
        release_date_str = upcoming.get("release_date")
        if not release_date_str:
            ttl = 86400
        else:
            try:
                release_date = datetime.fromisoformat(release_date_str).date()
                today = date.today()
                days_until = (release_date - today).days
                if days_until < 0:
                    ttl = 3600
                elif days_until == 0:
                    ttl = 2 * 3600
                elif days_until == 1:
                    ttl = 12 * 3600
                else:
                    ttl = (days_until * 86400) + (2 * 3600)
            except (ValueError, TypeError):
                ttl = 86400
    set_cached(CacheType.UPCOMING_ARTIST, upcoming, suffix=cache_key, ttl=ttl)
    return upcoming