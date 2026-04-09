from __future__ import annotations

from services.db_protocol import DBClient
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType

# -- Pure --
def build_featured_item(r: dict) -> dict:
    return {
        "album_id": r.get("album_id"),
        "album_name": r.get("album_name"),
        "artist_id": r.get("artist_id"),
        "artist_name": r.get("artist_name"),
        "release_date": r.get("release_date"),
        "thumbnail_url": r.get("thumbnail_url"),
        "track_count": r.get("track_count"),
        "play_count": r.get("play_count"),
    }

# -- IO --
def get_featured_new_release(db: DBClient, user_id: str) -> dict | None:
    try:
        res = db.rpc(
            "get_featured_new_release",
            {"p_user_id": user_id},
        ).execute()
        rows = getattr(res, "data", None) or []
    except Exception as e:
        print(f"[featured_service][get_featured_new_release][ERROR] {e}")
        return None

    if not rows:
        return None

    return build_featured_item(rows[0])

def get_featured_new_release_cached(db: DBClient, user_id: str) -> dict | None:
    cache_key = user_id
    cached = get_cached(CacheType.FEATURED_NEW_RELEASE, suffix=cache_key)
    if cached is not None:
        return cached

    featured = get_featured_new_release(db, user_id)
    set_cached(CacheType.FEATURED_NEW_RELEASE, featured, suffix=cache_key)
    return featured