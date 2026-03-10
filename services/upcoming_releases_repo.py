from __future__ import annotations
from datetime import date, datetime

from services.db_protocol import DBClient
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType

TABLE = "upcoming_releases"
FEED_TABLE = "feed_current"

def build_feed_set(rows: list) -> set:
    """Construye set de (artist, album) desde rows del feed."""
    feed_set = set()
    for row in rows:
        artist = (row.get("artist") or "").lower().strip()
        album = (row.get("album") or row.get("title") or "").lower().strip()
        if artist and album:
            feed_set.add((artist, album))
    return feed_set

def filter_releases_by_feed(releases: list, feed_set: set) -> list:
    """Filtra releases que NO están en feed_set."""
    if not feed_set:
        return releases

    filtered = []
    for release in releases:
        artist_name = (release.get("artist_name") or "").lower().strip()
        album_name = (release.get("album_name") or "").lower().strip()

        if artist_name and album_name:
            if (artist_name, album_name) not in feed_set:
                filtered.append(release)
        else:
            filtered.append(release)

    return filtered

def build_upcoming_item(r: dict) -> dict:
    return {
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
def _get_feed_releases_set(db: DBClient) -> set:
    """Obtiene TODOS los releases en feed_current como set de (artist, album)."""
    try:
        res = db.table(FEED_TABLE).select("artist, album, title").execute()
        rows = getattr(res, "data", None) or []
        return build_feed_set(rows)
    except Exception as e:
        print(f"[upcoming_repo][_get_feed_releases_set][ERROR] {e}")
        return set()

def _filter_releases_not_in_feed(db: DBClient, releases: list) -> list:
    """Filtra releases que ya están en feed_current."""
    if not releases:
        return []
    feed_set = _get_feed_releases_set(db)
    return filter_releases_by_feed(releases, feed_set)

def list_upcoming_releases(db: DBClient, include_tba: bool = True, limit: int = 50, filter_feed: bool = True) -> list:
    """Trae releases futuros (desde hoy en adelante)."""
    today = date.today().isoformat()
    fetch_limit = limit * 2 if filter_feed else limit

    try:
        q = db.table(TABLE).select("*")
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

    if filter_feed and releases:
        releases = _filter_releases_not_in_feed(db, releases)

    return releases[:limit]

def count_upcoming_releases(db: DBClient, filter_feed: bool = True) -> int:
    """Cuenta cuántos releases hay en total."""
    today = date.today().isoformat()
    try:
        res = db.table(TABLE).select("*").or_(f"release_date.gte.{today},is_tba.eq.true").execute()
        releases = getattr(res, "data", None) or []
    except Exception as e:
        print(f"[upcoming_repo][count_upcoming_releases][ERROR] {e}")
        return 0

    if filter_feed and releases:
        releases = _filter_releases_not_in_feed(db, releases)

    return len(releases)

def get_next_release_date(db: DBClient, filter_feed: bool = True) -> date | None:
    """Encuentra la fecha del próximo release (>=hoy) que NO esté en feed."""
    today = date.today()
    try:
        res = (
            db.table(TABLE)
            .select("*")
            .gte("release_date", today.isoformat())
            .order("release_date", desc=False)
            .limit(20)
            .execute()
        )
        rows = getattr(res, "data", []) or []
    except Exception as e:
        print(f"[upcoming_repo][get_next_release_date][ERROR] {e}")
        return None

    if not rows:
        return None

    if filter_feed:
        rows = _filter_releases_not_in_feed(db, rows)

    if not rows:
        return None

    return parse_release_date(rows[0].get("release_date"))

def calculate_smart_ttl(db: DBClient, filter_feed: bool = True) -> int:
    """Calcula TTL inteligente basado en próximo release."""
    next_release = get_next_release_date(db, filter_feed)
    return calculate_ttl_from_date(next_release)

def list_upcoming_releases_cached(db: DBClient, include_tba: bool = True, limit: int = 50, filter_feed: bool = True) -> list:
    """Versión cacheada con TTL inteligente."""
    cache_key = f"tba={include_tba}:limit={limit}:feed={filter_feed}"
    cached = get_cached(CacheType.UPCOMING_RELEASES, suffix=cache_key)
    if cached is not None:
        return cached

    releases = list_upcoming_releases(db, include_tba, limit, filter_feed)
    smart_ttl = calculate_smart_ttl(db, filter_feed)
    set_cached(CacheType.UPCOMING_RELEASES, releases, suffix=cache_key, ttl=smart_ttl)
    return releases

def get_upcoming_by_artist_id(db: DBClient, artist_id: str, filter_feed: bool = True) -> dict | None:
    """Devuelve el PRÓXIMO lanzamiento confirmado para un artista."""
    today = date.today().isoformat()
    try:
        q = (
            db.table(TABLE)
            .select("release_date, artist_name, album_name, label, thumbnail_url, track_count, artist_id")
            .eq("artist_id", artist_id)
            .gte("release_date", today)
            .or_("is_tba.is.false,is_tba.is.null")
            .order("release_date", desc=False)
            .limit(10)
        )
        res = q.execute()
        rows = getattr(res, "data", None) or []
    except Exception as e:
        print(f"[upcoming_repo][get_upcoming_by_artist_id][ERROR] {e}")
        return None

    if not rows:
        return None

    if filter_feed:
        rows = _filter_releases_not_in_feed(db, rows)
        if not rows:
            return None

    return build_upcoming_item(rows[0])

def get_upcoming_by_artist_id_cached(db: DBClient, artist_id: str, filter_feed: bool = True) -> dict | None:
    """Versión cacheada con TTL inteligente."""
    cache_key = f"{artist_id}:feed={filter_feed}"
    cached = get_cached(CacheType.UPCOMING_ARTIST, suffix=cache_key)
    if cached is not None:
        return cached

    upcoming = get_upcoming_by_artist_id(db, artist_id, filter_feed)

    if not upcoming:
        ttl = 7 * 86400
    else:
        release_date = parse_release_date(upcoming.get("release_date"))
        ttl = calculate_ttl_from_date(release_date)

    set_cached(CacheType.UPCOMING_ARTIST, upcoming, suffix=cache_key, ttl=ttl)
    return upcoming