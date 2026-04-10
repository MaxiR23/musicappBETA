from services.supabase_service import supabase_service
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType

def get_recommended_playlists(user_id: str, days: int = 45, limit: int = 5) -> list:
    cached = get_cached(CacheType.RECOMMENDED_PLAYLISTS, suffix=user_id)
    if cached is not None:
        return cached

    result = supabase_service.rpc("recommend_playlists_by_history", {
        "p_user_id": user_id,
        "p_days": days,
        "p_limit": limit,
    }).execute()

    data = result.data or []
    set_cached(CacheType.RECOMMENDED_PLAYLISTS, data, suffix=user_id)
    return data