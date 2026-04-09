from __future__ import annotations
from datetime import date, timedelta

from services.db_protocol import DBClient
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType

TABLE = "upcoming_releases"

def build_new_release_item(r: dict) -> dict:
    return {
        "album_id": r.get("album_id"),
        "release_date": r.get("release_date"),
        "artist": r.get("artist_name"),
        "album": r.get("album_name"),
        "thumbnail": r.get("thumbnail_url"),
        "artist_id": r.get("artist_id"),
    }

def list_new_releases(db: DBClient, limit: int = 30) -> list:
    """Albums released en los ultimos 30 dias."""
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    try:
        res = (
            db.table(TABLE)
            .select("album_id, release_date, artist_name, album_name, thumbnail_url, artist_id")
            .eq("status", "released")
            .gte("release_date", cutoff)
            .order("release_date", desc=True)
            .limit(limit)
            .execute()
        )
        return getattr(res, "data", None) or []
    except Exception as e:
        print(f"[new_releases_repo][list_new_releases][ERROR] {e}")
        return []

def list_new_releases_cached(db: DBClient, limit: int = 30) -> list:
    """Version cacheada."""
    cache_key = f"limit={limit}"
    cached = get_cached(CacheType.NEW_RELEASES, suffix=cache_key)
    if cached is not None:
        return cached

    releases = list_new_releases(db, limit)
    set_cached(CacheType.NEW_RELEASES, releases, suffix=cache_key)
    return releases