"""
Playlist service: lógica de negocio para playlists de usuario.
"""
from services.db_protocol import DBClient
from services.cache_service import get_cached, set_cached, invalidate
from services.cache_config import CacheType
from services.track_service import ensure_duration_seconds

# ── CACHE ─────────────────────────────────────────────────────────────────────
def _invalidate_playlist_cache(owner_id: str, playlist_id: str | None = None) -> None:
    invalidate(CacheType.USER_PLAYLISTS, suffix=owner_id)
    if playlist_id:
        invalidate(CacheType.USER_PLAYLISTS, suffix=f"{playlist_id}:{owner_id}")

# ── PLAYLISTS ──────────────────────────────────────────────────────────────────
def create_playlist(db: DBClient, user_id: str, title: str, description: str | None, is_public: bool) -> dict:
    resp = db.table("playlists").insert({
        "title": title,
        "description": description,
        "is_public": is_public,
        "owner_id": user_id,
    }).execute()
    _invalidate_playlist_cache(user_id)
    return resp.data[0]

def get_playlists(db: DBClient, user_id: str) -> list:
    cached = get_cached(CacheType.USER_PLAYLISTS, suffix=user_id)
    if cached is not None:
        return cached

    resp = db.table("playlists").select(
        "id,title,description,is_public,created_at,"
        "playlist_tracks(position,tracks(thumbnail_url))"
    ).eq("owner_id", user_id).order("created_at", desc=True).execute()

    payload = resp.data or []
    for pl in payload:
        if pl.get("playlist_tracks"):
            pl["playlist_tracks"].sort(key=lambda t: t.get("position") or 0)

    set_cached(CacheType.USER_PLAYLISTS, payload, suffix=user_id)
    return payload

def get_playlist_by_id(db: DBClient, user_id: str, playlist_id: str) -> dict | None:
    cache_suffix = f"{playlist_id}:{user_id}"
    cached = get_cached(CacheType.USER_PLAYLISTS, suffix=cache_suffix)
    if cached is not None:
        return cached

    playlist_resp = db.table("playlists").select("*").eq("id", playlist_id).single().execute()
    ptracks_resp = (
        db.table("playlist_tracks")
        .select("position,added_at,tracks(*)")
        .eq("playlist_id", playlist_id)
        .order("position")
        .execute()
    )

    payload = {
        **(playlist_resp.data or {}),
        "tracks": [
            {"position": row["position"], "added_at": row["added_at"], **row["tracks"]}
            for row in (ptracks_resp.data or [])
        ],
    }
    set_cached(CacheType.USER_PLAYLISTS, payload, suffix=cache_suffix)
    return payload

def delete_playlist(db: DBClient, user_id: str, playlist_id: str) -> list:
    db.table("playlist_tracks").delete().eq("playlist_id", playlist_id).execute()
    resp = db.table("playlists").delete().eq("id", playlist_id).eq("owner_id", user_id).execute()
    _invalidate_playlist_cache(user_id, playlist_id)
    return resp.data or []

# ── TRACKS ─────────────────────────────────────────────────────────────────────
def add_track(
    db: DBClient,
    service_db: DBClient,
    user_id: str,
    playlist_id: str,
    track_id: str,
    body: dict,
) -> dict:
    duration_seconds = ensure_duration_seconds(
        track_id=track_id,
        duration_seconds=body.get("duration_seconds"),
    )

    track_resp = service_db.table("tracks").upsert({
        "track_id": track_id,
        "title": body.get("title"),
        "artist": body.get("artist"),
        "artist_id": body.get("artist_id"),
        "album": body.get("album"),
        "album_id": body.get("album_id"),
        "duration_seconds": duration_seconds,
        "thumbnail_url": body.get("thumbnail_url"),
        "extra": body.get("extra"),
    }, on_conflict="track_id").execute()

    max_pos_resp = (
        db.table("playlist_tracks")
        .select("position")
        .eq("playlist_id", playlist_id)
        .order("position", desc=True)
        .limit(1)
        .execute()
    )
    last_pos = (max_pos_resp.data or [{}])[0].get("position") or 0

    link_resp = db.table("playlist_tracks").insert({
        "playlist_id": playlist_id,
        "track_id": track_resp.data[0]["id"],
        "position": last_pos + 1,
        "added_by": user_id,
    }).execute()

    _invalidate_playlist_cache(user_id, playlist_id)
    return {"track": track_resp.data[0], "link": link_resp.data[0]}

def remove_track(db: DBClient, user_id: str, playlist_id: str, track_id: str) -> None:
    db.table("playlist_tracks").delete().eq("playlist_id", playlist_id).eq("track_id", track_id).execute()
    _invalidate_playlist_cache(user_id, playlist_id)

def move_track(db: DBClient, user_id: str, playlist_id: str, old_index: int, new_index: int) -> dict:
    result = db.rpc("move_playlist_track", {
        "p_playlist_id": playlist_id,
        "p_old_index": old_index,
        "p_new_index": new_index,
    }).execute()

    data = result.data
    if not data or not data.get("ok"):
        raise ValueError(data or "rpc_failed")

    _invalidate_playlist_cache(user_id, playlist_id)
    return data