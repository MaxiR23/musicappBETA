from __future__ import annotations
from datetime import date, datetime

from services.db_protocol import DBClient
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType

TABLE = "upcoming_releases"

# ── Pure ─────────────────────────────────────────────────

def build_upcoming_item(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "release_date": r.get("release_date"),
        "artist": r.get("artist_name"),
        "album": r.get("album_name"),
        "label": r.get("label"),
        "thumbnail": r.get("thumbnail_url"),
        "track_count": r.get("track_count"),
        "artist_id": r.get("artist_id"),
    }

def calculate_ttl_from_date(release_date: date | None) -> int:
    """Calcula TTL basado en fecha de release."""
    if not release_date:
        return 7 * 86400

    today = date.today()
    days_until = (release_date - today).days

    if days_until < 0:
        return 3600
    if days_until == 0:
        return 2 * 3600
    if days_until == 1:
        return 12 * 3600
    return (days_until * 86400) + (2 * 3600)

def parse_release_date(release_date_str: str | None) -> date | None:
    if not release_date_str:
        return None
    try:
        return datetime.fromisoformat(release_date_str).date()
    except (ValueError, TypeError):
        return None

# ── IO ───────────────────────────────────────────────────

def list_upcoming_releases(db: DBClient, include_tba: bool = True, limit: int = 50) -> list:
    """Trae releases pending futuros (desde hoy en adelante)."""
    today = date.today().isoformat()

    try:
        q = db.table(TABLE).select("*").eq("status", "pending")
        if include_tba:
            q = q.or_(f"release_date.gte.{today},is_tba.eq.true")
        else:
            q = q.gte("release_date", today)
        q = q.order("is_tba", desc=False).order("release_date", desc=False).limit(limit)
        res = q.execute()
        return getattr(res, "data", None) or []
    except Exception as e:
        print(f"[upcoming_repo][list_upcoming_releases][ERROR] {e}")
        return []

def count_upcoming_releases(db: DBClient) -> int:
    """Cuenta cuantos releases pending hay."""
    today = date.today().isoformat()
    try:
        res = (
            db.table(TABLE)
            .select("*")
            .eq("status", "pending")
            .or_(f"release_date.gte.{today},is_tba.eq.true")
            .execute()
        )
        return len(getattr(res, "data", None) or [])
    except Exception as e:
        print(f"[upcoming_repo][count_upcoming_releases][ERROR] {e}")
        return 0

def get_next_release_date(db: DBClient) -> date | None:
    """Encuentra la fecha del proximo release pending (>=hoy)."""
    today = date.today()
    try:
        res = (
            db.table(TABLE)
            .select("release_date")
            .eq("status", "pending")
            .gte("release_date", today.isoformat())
            .order("release_date", desc=False)
            .limit(1)
            .execute()
        )
        rows = getattr(res, "data", []) or []
    except Exception as e:
        print(f"[upcoming_repo][get_next_release_date][ERROR] {e}")
        return None

    if not rows:
        return None

    return parse_release_date(rows[0].get("release_date"))

def calculate_smart_ttl(db: DBClient) -> int:
    """Calcula TTL inteligente basado en proximo release."""
    next_release = get_next_release_date(db)
    return calculate_ttl_from_date(next_release)

def list_upcoming_releases_cached(db: DBClient, include_tba: bool = True, limit: int = 50) -> list:
    """Version cacheada con TTL inteligente."""
    cache_key = f"tba={include_tba}:limit={limit}"
    cached = get_cached(CacheType.UPCOMING_RELEASES, suffix=cache_key)
    if cached is not None:
        return cached

    releases = list_upcoming_releases(db, include_tba, limit)
    smart_ttl = calculate_smart_ttl(db)
    set_cached(CacheType.UPCOMING_RELEASES, releases, suffix=cache_key, ttl=smart_ttl)
    return releases

def get_upcoming_by_artist_id(db: DBClient, artist_id: str) -> dict | None:
    """Devuelve el proximo lanzamiento pending para un artista."""
    today = date.today().isoformat()
    try:
        q = (
            db.table(TABLE)
            .select("id, release_date, artist_name, album_name, label, thumbnail_url, track_count, artist_id")
            .eq("artist_id", artist_id)
            .eq("status", "pending")
            .gte("release_date", today)
            .or_("is_tba.is.false,is_tba.is.null")
            .order("release_date", desc=False)
            .limit(1)
        )
        res = q.execute()
        rows = getattr(res, "data", None) or []
    except Exception as e:
        print(f"[upcoming_repo][get_upcoming_by_artist_id][ERROR] {e}")
        return None

    if not rows:
        return None

    return build_upcoming_item(rows[0])

def get_upcoming_by_artist_id_cached(db: DBClient, artist_id: str) -> dict | None:
    """Version cacheada con TTL inteligente."""
    cache_key = artist_id
    cached = get_cached(CacheType.UPCOMING_ARTIST, suffix=cache_key)
    if cached is not None:
        return cached

    upcoming = get_upcoming_by_artist_id(db, artist_id)

    if not upcoming:
        ttl = 7 * 86400
    else:
        release_date = parse_release_date(upcoming.get("release_date"))
        ttl = calculate_ttl_from_date(release_date)

    set_cached(CacheType.UPCOMING_ARTIST, upcoming, suffix=cache_key, ttl=ttl)
    return upcoming

def list_upcoming_30d(db: DBClient) -> list:
    """Trae releases pending de hoy + 30 dias."""
    from datetime import timedelta

    today = date.today()
    end = today + timedelta(days=30)

    try:
        res = (
            db.table(TABLE)
            .select("*")
            .eq("status", "pending")
            .gte("release_date", today.isoformat())
            .lte("release_date", end.isoformat())
            .order("release_date", desc=False)
            .execute()
        )
        return getattr(res, "data", None) or []
    except Exception as e:
        print(f"[upcoming_repo][list_upcoming_30d][ERROR] {e}")
        return []

def list_upcoming_30d_cached(db: DBClient) -> list:
    """Version cacheada. TTL = smart basado en proximo release."""
    cache_key = "upcoming_30d"
    cached = get_cached(CacheType.UPCOMING_RELEASES, suffix=cache_key)
    if cached is not None:
        return cached

    releases = list_upcoming_30d(db)
    smart_ttl = calculate_smart_ttl(db)
    set_cached(CacheType.UPCOMING_RELEASES, releases, suffix=cache_key, ttl=smart_ttl)
    return releases

# ── Status updates (para cron y check en tiempo real) ────
def mark_as_released(db: DBClient, release_id: str, album_id: str | None = None) -> bool:
    """Marca un release como confirmado, opcionalmente guarda album_id."""
    try:
        payload = {
            "status": "released",
            "confirmed_at": datetime.now().isoformat(),
        }
        if album_id:
            payload["album_id"] = album_id
        db.table(TABLE).update(payload).eq("id", release_id).execute()
        return True
    except Exception as e:
        print(f"[upcoming_repo][mark_as_released][ERROR] {e}")
        return False

def mark_as_postponed(db: DBClient, release_id: str) -> bool:
    """Marca un release como postergado."""
    try:
        db.table(TABLE).update({
            "status": "postponed",
            "confirmed_at": datetime.now().isoformat(),
        }).eq("id", release_id).execute()
        return True
    except Exception as e:
        print(f"[upcoming_repo][mark_as_postponed][ERROR] {e}")
        return False

def get_todays_pending(db: DBClient) -> list:
    """Trae releases de hoy que siguen pending (para el cron)."""
    today = date.today().isoformat()
    try:
        res = (
            db.table(TABLE)
            .select("*")
            .eq("status", "pending")
            .eq("release_date", today)
            .execute()
        )
        return getattr(res, "data", None) or []
    except Exception as e:
        print(f"[upcoming_repo][get_todays_pending][ERROR] {e}")
        return []
    
def get_released_and_postponed_keys(db: DBClient) -> set:
    """Keys (artist_name, album_name) de released/postponed. El sync los salta."""
    try:
        res = (
            db.table(TABLE)
            .select("artist_name, album_name")
            .in_("status", ["released", "postponed"])
            .execute()
        )
        rows = getattr(res, "data", None) or []
        return {(r["artist_name"], r["album_name"]) for r in rows}
    except Exception as e:
        print(f"[upcoming_repo][get_released_and_postponed_keys][ERROR] {e}")
        return set()
    
def get_all_pending(db: DBClient) -> dict:
    """Trae todos los pending indexados por (artist_name, album_name).
    El sync lo usa para decidir si actualizar metadata."""
    try:
        res = (
            db.table(TABLE)
            .select("id, artist_name, album_name, artist_id, thumbnail_url, track_count, release_date, is_tba")
            .eq("status", "pending")
            .execute()
        )
        rows = getattr(res, "data", None) or []
        return {
            (r["artist_name"], r["album_name"]): r
            for r in rows
        }
    except Exception as e:
        print(f"[upcoming_repo][get_all_pending][ERROR] {e}")
        return {}
    
def insert_release(db: DBClient, row: dict) -> bool:
    """Inserta un release nuevo."""
    try:
        db.table(TABLE).insert(row).execute()
        return True
    except Exception as e:
        print(f"[upcoming_repo][insert_release][ERROR] {e}")
        return False
    
def update_release_metadata(db: DBClient, release_id: str, updates: dict) -> bool:
    """Actualiza metadata de un release pending (thumbnail, date, etc)."""
    if not updates:
        return True
    try:
        db.table(TABLE).update(updates).eq("id", release_id).execute()
        return True
    except Exception as e:
        print(f"[upcoming_repo][update_release_metadata][ERROR] {e}")
        return False
    
def log_sync_error(db: DBClient, artist_name: str, album_name: str, error_type: str, error_detail: str | None = None) -> None:
    """Registra un error de sync en release_sync_errors."""
    try:
        db.table("release_sync_errors").insert({
            "artist_name": artist_name,
            "album_name": album_name,
            "error_type": error_type,
            "error_detail": error_detail,
        }).execute()
    except Exception as e:
        print(f"[upcoming_repo][log_sync_error][ERROR] {e}")