from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path
from fastapi.responses import JSONResponse

from core.dependencies import get_user_db, get_service_db, get_current_user_id
from services.db_protocol import DBClient
from services.cache_service import get_cached, set_cached, invalidate
from services.cache_config import CacheType
from services.track_service import ensure_duration_seconds

router = APIRouter(tags=["playlists"])

# ── HELPERS ──────────────────────────────────────────────
def _invalidate_playlist_cache(owner_id: str, playlist_id: str | None = None) -> None:
    invalidate(CacheType.USER_PLAYLISTS, suffix=owner_id)
    if playlist_id:
        invalidate(CacheType.USER_PLAYLISTS, suffix=f"{playlist_id}:{owner_id}")

# ── PLAYLISTS ─────────────────────────────────────────────
@router.post("/")
async def create_playlist(
    body: dict = Body(...),
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    title = body.get("title")
    if not title:
        return JSONResponse(status_code=400, content={"error": "title_required"})
    try:
        resp = db.table("playlists").insert({
            "title": title,
            "description": body.get("description"),
            "is_public": body.get("is_public", False),
            "owner_id": user_id,
        }).execute()
        _invalidate_playlist_cache(user_id)
        return resp.data[0]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "db_error", "detail": str(e)})

@router.get("/")
async def get_playlists(
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    cached = get_cached(CacheType.USER_PLAYLISTS, suffix=user_id)
    if cached:
        return cached
    try:
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
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "db_error", "detail": str(e)})

@router.get("/{playlist_id}")
async def get_playlist_by_id(
    playlist_id: str,
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    cache_suffix = f"{playlist_id}:{user_id}"
    cached = get_cached(CacheType.USER_PLAYLISTS, suffix=cache_suffix)
    if cached:
        return cached
    try:
        playlist_resp = db.table("playlists").select("*").eq("id", playlist_id).single().execute()
        ptracks_resp = db.table("playlist_tracks") \
            .select("position,added_at,tracks(*)") \
            .eq("playlist_id", playlist_id) \
            .order("position") \
            .execute()

        payload = {
            **(playlist_resp.data or {}),
            "tracks": [
                {"position": row["position"], "added_at": row["added_at"], **row["tracks"]}
                for row in (ptracks_resp.data or [])
            ],
        }
        set_cached(CacheType.USER_PLAYLISTS, payload, suffix=cache_suffix)
        return payload
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "db_error", "detail": str(e)})

@router.post("/{playlist_id}/tracks")
async def add_track_to_playlist(
    playlist_id: str,
    body: dict = Body(...),
    db: DBClient = Depends(get_user_db),          # RLS: operaciones de playlist del usuario
    service_db: DBClient = Depends(get_service_db), # service role: upsert de track compartido
    user_id: str = Depends(get_current_user_id),
):
    track_id = body.get("track_id")
    if not track_id:
        return JSONResponse(status_code=400, content={"error": "track_id_required"})
    try:
        duration_seconds = ensure_duration_seconds(
            track_id=track_id,
            duration_seconds=body.get("duration_seconds"),
        )
        # Upsert del track con service role (tracks son datos compartidos)
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

        # Posición siguiente con RLS del usuario
        max_pos_resp = db.table("playlist_tracks") \
            .select("position") \
            .eq("playlist_id", playlist_id) \
            .order("position", desc=True) \
            .limit(1) \
            .execute()
        last_pos = (max_pos_resp.data or [{}])[0].get("position") or 0
        pos = last_pos + 1

        link_resp = db.table("playlist_tracks").insert({
            "playlist_id": playlist_id,
            "track_id": track_resp.data[0]["id"],
            "position": pos,
            "added_by": user_id,
        }).execute()

        _invalidate_playlist_cache(user_id, playlist_id)
        return {"ok": True, "track": track_resp.data[0], "link": link_resp.data[0]}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "db_error", "detail": str(e)})

@router.delete("/{playlist_id}/tracks/{track_id}")
async def remove_track_from_playlist(
    playlist_id: str,
    track_id: str,
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    try:
        db.table("playlist_tracks") \
            .delete().eq("playlist_id", playlist_id).eq("track_id", track_id).execute()
        _invalidate_playlist_cache(user_id, playlist_id)
        return {"ok": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "db_error", "detail": str(e)})

@router.delete("/{playlist_id}")
async def delete_playlist(
    playlist_id: str,
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    try:
        db.table("playlist_tracks").delete().eq("playlist_id", playlist_id).execute()
        resp = db.table("playlists").delete().eq("id", playlist_id).eq("owner_id", user_id).execute()
        _invalidate_playlist_cache(user_id, playlist_id)
        return {"ok": True, "deleted": resp.data or []}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "db_error", "detail": str(e)})

# TODO: fix reorder or improve with new endpoint and optimistic UI in frontend
@router.post("/{playlist_id}/move-track")
def move_playlist_track(
    playlist_id: str = Path(...),
    body: dict = Body(...),
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    old_index = body.get("old_position")
    new_index = body.get("new_position")

    if not isinstance(old_index, int) or not isinstance(new_index, int) \
       or old_index < 1 or new_index < 1:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid_params"})
    try:
        result = db.rpc("move_playlist_track", {
            "p_playlist_id": playlist_id,
            "p_old_index": old_index,
            "p_new_index": new_index,
        }).execute()

        data = result.data
        if not data or not data.get("ok"):
            return JSONResponse(status_code=400, content=data or {"ok": False, "error": "rpc_failed"})

        _invalidate_playlist_cache(user_id, playlist_id)
        return data
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "move_failed", "detail": str(e)})