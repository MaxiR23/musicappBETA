from datetime import date, timedelta
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType

def _get_last_month_start() -> date:
    first_of_current = date.today().replace(day=1)
    return (first_of_current - timedelta(days=1)).replace(day=1)

def _get_monthly_stats(db, user_id: str, entity_type: str, limit: int = None) -> list:
    cache_suffix = f"{user_id}:{entity_type}"

    cached = get_cached(CacheType.MONTHLY_STATS, suffix=cache_suffix)
    if cached is not None:
        return cached[:limit] if limit else cached

    month = _get_last_month_start()

    try:
        resp = db.table("user_monthly_stats") \
            .select("stats") \
            .eq("user_id", user_id) \
            .eq("entity_type", entity_type) \
            .eq("month", month.isoformat()) \
            .maybe_single() \
            .execute()

        stats = (resp.data or {}).get("stats") or [] if resp else []
        set_cached(CacheType.MONTHLY_STATS, stats, suffix=cache_suffix)

        return stats[:limit] if limit else stats
    except Exception as e:
        print(f"[monthly_stats][ERROR] {entity_type} for {user_id}: {e}")
        return []

def get_monthly_artists(db, user_id: str, limit: int = None) -> list:
    return _get_monthly_stats(db, user_id, "artist", limit=limit)

def get_monthly_albums(db, user_id: str, limit: int = None) -> list:
    return _get_monthly_stats(db, user_id, "album", limit=limit)

def get_monthly_tracks(db, user_id: str, limit: int = None) -> list:
    return _get_monthly_stats(db, user_id, "track", limit=limit)

def get_monthly_summary(db, user_id: str, include: str = None, limit: int = None) -> dict:
    types = [t.strip() for t in include.split(",")] if include else ["artists", "albums", "tracks"]

    result = {"month_start": _get_last_month_start().isoformat()}

    if "artists" in types:
        result["artists"] = get_monthly_artists(db, user_id, limit)
    if "albums" in types:
        result["albums"] = get_monthly_albums(db, user_id, limit)
    if "tracks" in types:
        result["tracks"] = get_monthly_tracks(db, user_id, limit)

    return result