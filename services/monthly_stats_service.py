from __future__ import annotations
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from services.db_protocol import DBClient
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType

def get_last_month_start() -> date:
    first_of_current = date.today().replace(day=1)
    return (first_of_current - timedelta(days=1)).replace(day=1)

def build_cache_suffix(user_id: str, entity_type: str) -> str:
    return f"{user_id}:{entity_type}"

def extract_stats_from_response(resp: Any) -> List[Dict[str, Any]]:
    if not resp:
        return []
    return (resp.data or {}).get("stats") or []

def slice_stats(stats: List[Dict[str, Any]], limit: Optional[int]) -> List[Dict[str, Any]]:
    return stats[:limit] if limit else stats

def parse_include_types(include: Optional[str]) -> List[str]:
    if not include:
        return ["artists", "albums", "tracks"]
    return [t.strip() for t in include.split(",")]

# ── IO ───────────────────────────────────────────────────
def _get_monthly_stats(db: DBClient, user_id: str, entity_type: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    cache_suffix = build_cache_suffix(user_id, entity_type)

    cached = get_cached(CacheType.MONTHLY_STATS, suffix=cache_suffix)
    if cached is not None:
        return slice_stats(cached, limit)

    month = get_last_month_start()

    try:
        resp = db.table("user_monthly_stats") \
            .select("stats") \
            .eq("user_id", user_id) \
            .eq("entity_type", entity_type) \
            .eq("month", month.isoformat()) \
            .maybe_single() \
            .execute()

        stats = extract_stats_from_response(resp)
        set_cached(CacheType.MONTHLY_STATS, stats, suffix=cache_suffix)
        return slice_stats(stats, limit)
    except Exception as e:
        print(f"[monthly_stats][ERROR] {entity_type} for {user_id}: {e}")
        return []

def get_monthly_artists(db: DBClient, user_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    return _get_monthly_stats(db, user_id, "artist", limit=limit)

def get_monthly_albums(db: DBClient, user_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    return _get_monthly_stats(db, user_id, "album", limit=limit)

def get_monthly_tracks(db: DBClient, user_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    return _get_monthly_stats(db, user_id, "track", limit=limit)

def get_monthly_summary(db: DBClient, user_id: str, include: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    types = parse_include_types(include)
    result: Dict[str, Any] = {"month_start": get_last_month_start().isoformat()}

    if "artists" in types:
        result["artists"] = get_monthly_artists(db, user_id, limit)
    if "albums" in types:
        result["albums"] = get_monthly_albums(db, user_id, limit)
    if "tracks" in types:
        result["tracks"] = get_monthly_tracks(db, user_id, limit)

    return result