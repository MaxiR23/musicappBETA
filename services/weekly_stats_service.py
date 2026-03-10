from __future__ import annotations
from datetime import date, timedelta

from services.db_protocol import DBClient
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType

def get_week_start(d: date | None = None) -> date:
    """Lunes de la semana PASADA (la última cerrada)."""
    d = d or date.today()
    current_monday = d - timedelta(days=d.weekday())
    return current_monday - timedelta(days=7)

def build_cache_suffix(user_id: str, entity_type: str) -> str:
    return f"{user_id}:{entity_type}"

def extract_stats_from_response(resp) -> list:
    if not resp:
        return []
    return (resp.data or {}).get("stats") or []

def slice_stats(stats: list, limit: int | None) -> list:
    return stats[:limit] if limit else stats

def parse_include_types(include: str | None) -> list:
    if not include:
        return ["artists", "albums", "tracks"]
    return [t.strip() for t in include.split(",")]

# ── IO ───────────────────────────────────────────────────
def get_weekly_stats(db: DBClient, user_id: str, entity_type: str, limit: int | None = None) -> list:
    cache_suffix = build_cache_suffix(user_id, entity_type)

    cached = get_cached(CacheType.WEEKLY_STATS, suffix=cache_suffix)
    if cached is not None:
        return slice_stats(cached, limit)

    week = get_week_start()

    try:
        resp = db.table("user_weekly_stats") \
            .select("stats") \
            .eq("user_id", user_id) \
            .eq("entity_type", entity_type) \
            .eq("week_start", week.isoformat()) \
            .maybe_single() \
            .execute()

        stats = extract_stats_from_response(resp)
        set_cached(CacheType.WEEKLY_STATS, stats, suffix=cache_suffix)
        return slice_stats(stats, limit)
    except Exception as e:
        print(f"[weekly_stats][ERROR] {entity_type} for {user_id}: {e}")
        return []

def get_weekly_artists(db: DBClient, user_id: str, limit: int | None = None) -> list:
    return get_weekly_stats(db, user_id, "artist", limit=limit)

def get_weekly_albums(db: DBClient, user_id: str, limit: int | None = None) -> list:
    return get_weekly_stats(db, user_id, "album", limit=limit)

def get_weekly_tracks(db: DBClient, user_id: str, limit: int | None = None) -> list:
    return get_weekly_stats(db, user_id, "track", limit=limit)

def get_weekly_summary(db: DBClient, user_id: str, include: str | None = None, limit: int | None = None) -> dict:
    """include: None (todo) o "artists" o "artists,albums,tracks"."""
    types = parse_include_types(include)
    result = {"week_start": get_week_start().isoformat()}

    if "artists" in types:
        result["artists"] = get_weekly_artists(db, user_id, limit)
    if "albums" in types:
        result["albums"] = get_weekly_albums(db, user_id, limit)
    if "tracks" in types:
        result["tracks"] = get_weekly_tracks(db, user_id, limit)

    return result