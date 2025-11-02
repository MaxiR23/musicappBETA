# services/upcoming_releases_repo.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
from datetime import date,  datetime

from services.supabase_service import supabase_service as sb
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType

TABLE = "upcoming_releases"

def list_upcoming_releases(
    include_tba: bool = True,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Trae releases futuros (desde hoy en adelante).
    Si include_tba=True, también trae los TBA.
    """
    today = date.today().isoformat()  # '2025-11-05'
    
    q = sb.table(TABLE).select("*")
    
    if include_tba:
        # release_date >= hoy OR is_tba = true
        q = q.or_(f"release_date.gte.{today},is_tba.eq.true")
    else:
        # Solo con fecha >= hoy
        q = q.gte("release_date", today)
    
    # Ordenar: TBAs al final, luego por fecha ascendente
    q = q.order("is_tba", desc=False).order("release_date", desc=False)
    q = q.limit(limit)
    
    res = q.execute()
    return getattr(res, "data", None) or []

def count_upcoming_releases() -> int:
    """Cuenta cuántos releases hay en total (para stats)"""
    today = date.today().isoformat()
    res = sb.table(TABLE).select("id", count="exact") \
        .or_(f"release_date.gte.{today},is_tba.eq.true") \
        .execute()
    return getattr(res, "count", 0) or 0

def get_next_release_date() -> date | None:
    """
    Encuentra la fecha del próximo release (>=hoy).
    Devuelve None si no hay más releases.
    """
    today = date.today()
    
    res = sb.table(TABLE).select("release_date") \
        .gte("release_date", today.isoformat()) \
        .order("release_date", desc=False) \
        .limit(1) \
        .execute()
    
    rows = getattr(res, "data", [])
    if not rows:
        return None
    
    release_str = rows[0].get("release_date")
    if not release_str:
        return None
    
    return datetime.fromisoformat(release_str).date()


def calculate_smart_ttl() -> int:
    """
    Calcula TTL inteligente:
    - Si hay próximo release: TTL = días hasta ese release + 2 horas
    - Si NO hay: TTL = 7 días (default)
    """
    next_release = get_next_release_date()
    
    if not next_release:
        # No hay más releases, cachea 7 días
        return 7 * 86400
    
    today = date.today()
    days_until = (next_release - today).days
    
    if days_until <= 0:
        # El release es HOY, cachea 2 horas (para que se actualice durante el día)
        return 2 * 3600
    
    # Cachea hasta el día del release + 2 horas de margen
    # (expira a las ~2am del día del release)
    return (days_until * 86400) + (2 * 3600)

def list_upcoming_releases_cached(
    include_tba: bool = True,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Versión cacheada con TTL inteligente.
    El caché expira solo cuando hay un nuevo release.
    """
    cache_key = f"tba={include_tba}:limit={limit}"
    
    # Intenta leer del caché
    cached = get_cached(CacheType.UPCOMING_RELEASES, suffix=cache_key)
    if cached is not None:
        return cached
    
    # Cache miss - consulta DB
    releases = list_upcoming_releases(include_tba, limit)
    
    # Calcula TTL inteligente
    smart_ttl = calculate_smart_ttl()
    
    # Cachea con el TTL dinámico
    set_cached(CacheType.UPCOMING_RELEASES, releases, suffix=cache_key, ttl=smart_ttl)
    
    print(f"[UPCOMING_RELEASES] Cacheado por {smart_ttl // 3600}h ({smart_ttl}s)")
    
    return releases

def get_upcoming_by_artist_id(artist_id: str) -> Optional[Dict[str, Any]]:
    """
    Devuelve el PRÓXIMO lanzamiento confirmado (no-TBA) para un artista dado su `artist_id`.

    Definición de “próximo”:
      - `release_date` >= hoy (fecha actual, en ISO YYYY-MM-DD).
      - Excluye explícitamente filas marcadas como TBA (`is_tba = true`).
      - Acepta filas donde `is_tba` sea `false` o `NULL` (muchos scrapers no setean el boolean).
      - Ordena ascendente por fecha y devuelve SOLO la primera (la más cercana).

    Columnas esperadas en la tabla `upcoming_releases`:
      - artist_id        (str)  -> browseId/canonical ID de YouTube Music (channel/browse, ya normalizado).
      - artist_name      (str)
      - album_name       (str)
      - release_date     (date) -> NULL si es TBA.
      - is_tba           (bool) -> true/false/NULL (NULL se trata como “no TBA”).
      - label            (str | NULL)
      - thumbnail_url    (str | NULL)
      - track_count      (int | NULL)

    Returns:
      dict con {release_date, artist, album, label, thumbnail, track_count, artist_id}
      o None si no hay próximos lanzamientos que cumplan las condiciones.
    """
    today = date.today().isoformat()

    # Query exacta por artist_id:
    #  - Filtra a futuro (>= hoy)
    #  - Excluye TBA (permite false o NULL)
    #  - Ordena por fecha ascendente y limita a 1
    q = (
        sb.table(TABLE)
        .select("release_date, artist_name, album_name, label, thumbnail_url, track_count, artist_id")
        .eq("artist_id", artist_id)                     # match estricto por ID correcto
        .gte("release_date", today)                     # solo presentes/futuros
        .or_("is_tba.is.false,is_tba.is.null")          # NO TBA
        .order("release_date", desc=False)              # el más próximo primero
        .limit(1)
    )

    # Ejecuta y recoge filas (tolerante si la lib cambia la forma de 'data')
    res = q.execute()
    rows = getattr(res, "data", None) or []
    if not rows:
        return None

    r = rows[0]
    # Normaliza claves de salida a las usadas por el frontend
    return {
        "release_date": r.get("release_date"),
        "artist":       r.get("artist_name"),
        "album":        r.get("album_name"),
        "label":        r.get("label"),
        "thumbnail":    r.get("thumbnail_url"),
        "track_count":  r.get("track_count"),
        "artist_id":    r.get("artist_id"),
    }