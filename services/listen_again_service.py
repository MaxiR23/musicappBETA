# services/listen_again_service.py
"""
Listen Again — album más escuchado que el usuario no tocó en 7+ días.
"""
from __future__ import annotations

from services.db_protocol import DBClient
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType

def get_listen_again(db: DBClient, user_id: str) -> dict | None:
    """Trae el album top sin escuchar en 7+ días via RPC."""
    try:
        res = db.rpc("get_listen_again", {"p_user_id": user_id}).execute()
        rows = getattr(res, "data", None) or []
        return rows[0] if rows else None
    except Exception as e:
        print(f"[listen_again][ERROR] {e}")
        return None

def get_listen_again_cached(db: DBClient, user_id: str) -> dict | None:
    """Version cacheada por user_id."""
    cached = get_cached(CacheType.LISTEN_AGAIN, suffix=user_id)
    if cached is not None:
        return cached

    result = get_listen_again(db, user_id)
    set_cached(CacheType.LISTEN_AGAIN, result, suffix=user_id)
    return result