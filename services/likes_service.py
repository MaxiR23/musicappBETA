"""
Likes service: logica de negocio para likes de tracks.
"""
from datetime import datetime, timezone

from services.db_protocol import DBClient
from services.track_service import ensure_duration_seconds

from services.db_protocol import DBClient
from services.track_service import ensure_duration_seconds
from services.cache_service import get_cached, set_cached, invalidate
from services.cache_config import CacheType

# ── CACHE ──────────────────────────────────────────────────────────────────────
def _invalidate_liked_cache(user_id: str) -> None:
    invalidate(CacheType.LIKED_TRACKS, suffix=user_id)

# ── LIKE / UNLIKE ──────────────────────────────────────────────────────────────
def like_track(
    db: DBClient,
    service_db: DBClient,
    user_id: str,
    track_id: str,
    body: dict,
) -> dict:
    """
    Likear un track. Upsert en tracks (metadata) + upsert en user_likes.
    Soporta re-like: si el track fue unlikeado (soft delete), lo reactiva.
    """
    duration_seconds = ensure_duration_seconds(
        track_id=track_id,
        duration_seconds=body.get("duration_seconds"),
    )

    service_db.table("tracks").upsert(
        {
            "track_id": track_id,
            "title": body.get("title"),
            "artist": body.get("artist"),
            "artist_id": body.get("artist_id"),
            "album": body.get("album"),
            "album_id": body.get("album_id"),
            "duration_seconds": duration_seconds,
            "thumbnail_url": body.get("thumbnail_url"),
            "extra": body.get("extra"),
        },
        on_conflict="track_id",
    ).execute()

    now = datetime.now(timezone.utc).isoformat()
    resp = (
        db.table("user_likes")
        .upsert(
            {
                "user_id": user_id,
                "track_id": track_id,
                "updated_at": now,
                "deleted_at": None,
            },
            on_conflict="user_id,track_id",
        )
        .execute()
    )

    _invalidate_liked_cache(user_id)
    return resp.data[0]

def unlike_track(db: DBClient, user_id: str, track_id: str) -> None:
    """
    Soft delete: marca deleted_at en vez de borrar la fila.
    Solo actua sobre likes activos (deleted_at is null).
    """
    now = datetime.now(timezone.utc).isoformat()
    db.table("user_likes").update(
        {
            "deleted_at": now,
            "updated_at": now,
        }
    ).eq("user_id", user_id).eq("track_id", track_id).is_("deleted_at", "null").execute()
    _invalidate_liked_cache(user_id)

# ── QUERIES ────────────────────────────────────────────────────────────────────
def get_likes(db: DBClient, user_id: str) -> list:
    """Todos los likes activos del usuario, con metadata del track."""
    resp = (
        db.table("user_likes")
        .select("track_id,created_at,tracks(*)")
        .eq("user_id", user_id)
        .is_("deleted_at", "null")
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data or []

def get_likes_sync(db: DBClient, user_id: str, since: str) -> list:
    """
    Delta sync: cambios desde `since` (ISO timestamp).
    Retorna likes activos Y soft-deleted para que el frontend
    sepa que agregar y que borrar de SQLite.
    """
    resp = (
        db.table("user_likes")
        .select("track_id,created_at,updated_at,deleted_at,tracks(*)")
        .eq("user_id", user_id)
        .gt("updated_at", since)
        .order("updated_at")
        .execute()
    )
    return resp.data or []

# ── LIKED PLAYLIST ─────────────────────────────────────────────────────────────
def get_liked_playlist(db: DBClient, user_id: str) -> dict:
    """
    Playlist virtual con todos los likes activos del usuario.
    Devuelve el mismo shape que get_playlist_by_id para que el front
    lo trate como cualquier playlist.
    """
    cached = get_cached(CacheType.LIKED_TRACKS, suffix=user_id)
    if cached is not None:
        return cached

    resp = (
        db.table("user_likes")
        .select("track_id,created_at,tracks(*)")
        .eq("user_id", user_id)
        .is_("deleted_at", "null")
        .order("created_at", desc=False)
        .execute()
    )

    rows = resp.data or []
    tracks = []
    for i, row in enumerate(rows):
        t = row.get("tracks") or {}
        tracks.append({
            "id": t.get("id"),
            "track_id": row["track_id"],
            "title": t.get("title"),
            "artist": t.get("artist"),
            "artist_id": t.get("artist_id"),
            "album_id": t.get("album_id"),
            "album_name": t.get("album"),
            "duration_seconds": t.get("duration_seconds"),
            "thumbnail_url": t.get("thumbnail_url"),
            "position": i + 1,
            "added_at": row.get("created_at"),
        })

    payload = {
        "id": "liked",
        "title": "Liked Songs",
        "description": None,
        "is_public": False,
        "tracks": tracks,
    }

    set_cached(CacheType.LIKED_TRACKS, payload, suffix=user_id)
    return payload