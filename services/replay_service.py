"""
Lógica de negocio para la playlist "Replay".
Canciones más repetidas por el usuario según play_events.
"""
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType, DEFAULT_TTL
from services.db_protocol import DBClient

REPLAY_MIN_PLAYS = 3
REPLAY_LIMIT = 20
REPLAY_MIN_SONGS_TO_SHOW = 10


def get_replay_songs(db: DBClient, user_id: str) -> list:
    cached = get_cached(CacheType.REPLAY, suffix=user_id)
    if cached is not None:
        return cached

    result = db.rpc("get_replay_songs", {
        "p_user_id":   user_id,
        "p_min_plays": REPLAY_MIN_PLAYS,
        "p_limit":     REPLAY_LIMIT,
    }).execute()

    songs = result.data or []

    if len(songs) < REPLAY_MIN_SONGS_TO_SHOW:
        songs = []

    set_cached(CacheType.REPLAY, songs, suffix=user_id)
    return songs