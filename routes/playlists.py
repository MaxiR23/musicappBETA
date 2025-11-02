# routes/playlists.py
from fastapi import APIRouter, Request, Body
from services.supabase_service import db_as_user, supabase_service
from services.cache_service import get_cached_legacy, set_cached_legacy, invalidate
from services.cache_config import CacheType
from services.jwt_utils import decode_jwt

router = APIRouter(tags=["playlists"])

def _get_user_id(request: Request) -> str | None:
    user = getattr(request.state, "user", None)
    if isinstance(user, dict) and user.get("id"):
        return user["id"]
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    claims = decode_jwt(token) or {}
    return claims.get("sub")

@router.post("/")
async def create_playlist(request: Request, body: dict = Body(...)):
    jwt = request.headers.get("Authorization", "").replace("Bearer ", "")
    db = db_as_user(jwt)

    title = body.get("title")
    description = body.get("description")
    is_public = body.get("is_public", False)

    if not title:
        return {"error": "title requerido"}

    owner_id = _get_user_id(request)
    if not owner_id:
        return {"error": "unauthorized"}

    try:
        resp = db.table("playlists").insert({
            "title": title,
            "description": description,
            "is_public": is_public,
            "owner_id": owner_id,
        }).execute()
        
        invalidate(CacheType.USER_PLAYLISTS, suffix=owner_id)
        return resp.data[0]
    except Exception as e:
        return {"error": "db_error", "detail": str(e)}

@router.get("/")
async def get_playlists(request: Request):
    jwt = request.headers.get("Authorization", "").replace("Bearer ", "")
    db = db_as_user(jwt)

    owner_id = _get_user_id(request)
    if not owner_id:
        return {"error": "unauthorized"}

    cached = get_cached_legacy(CacheType.USER_PLAYLISTS, suffix=owner_id)
    if cached:
        return cached

    try:
        resp = db.table("playlists").select(
            "id,title,description,is_public,created_at,"
            "playlist_tracks(position,tracks(thumbnail_url))"
        ).eq("owner_id", owner_id) \
         .order("created_at", desc=True) \
         .execute()

        payload = resp.data or []

        for pl in payload:
            if "playlist_tracks" in pl and pl["playlist_tracks"]:
                pl["playlist_tracks"].sort(key=lambda t: t.get("position") or 0)

        set_cached_legacy(CacheType.USER_PLAYLISTS, payload, suffix=owner_id)
        return payload
    except Exception as e:
        return {"error": "db_error", "detail": str(e)}

@router.get("/{playlist_id}")
async def get_playlist_by_id(request: Request, playlist_id: str):
    jwt = request.headers.get("Authorization", "").replace("Bearer ", "")
    db = db_as_user(jwt)

    owner_id = _get_user_id(request)
    cache_suffix = f"{playlist_id}:{owner_id}" if owner_id else playlist_id
    
    cached = get_cached_legacy(CacheType.USER_PLAYLISTS, suffix=cache_suffix)
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
            ]
        }

        set_cached_legacy(CacheType.USER_PLAYLISTS, payload, suffix=cache_suffix)
        return payload
    except Exception as e:
        return {"error": "db_error", "detail": str(e)}

@router.post("/{playlist_id}/tracks")
async def add_track_to_playlist(request: Request, playlist_id: str, body: dict = Body(...)):
    jwt = request.headers.get("Authorization", "").replace("Bearer ", "")
    db = db_as_user(jwt)

    track_id = body.get("track_id")
    if not track_id:
        return {"error": "track_id requerido"}

    added_by = _get_user_id(request)
    if not added_by:
        return {"error": "unauthorized"}

    try:
        track_resp = supabase_service.table("tracks").upsert({
            "track_id": track_id,
            "title": body.get("title"),
            "artist": body.get("artist"),
            "artist_id": body.get("artist_id"),
            "album": body.get("album"),
            "duration_ms": body.get("duration_ms"),
            "thumbnail_url": body.get("thumbnail_url"),
            "extra": body.get("extra"),
        }, on_conflict="track_id").execute()

        max_pos_resp = db.table("playlist_tracks") \
            .select("position") \
            .eq("playlist_id", playlist_id) \
            .order("position", desc=True) \
            .limit(1) \
            .execute()
        last_pos = 0
        if max_pos_resp.data and len(max_pos_resp.data) > 0:
            last_pos = max_pos_resp.data[0].get("position") or 0
        pos = (last_pos or 0) + 1

        link_resp = db.table("playlist_tracks").insert({
            "playlist_id": playlist_id,
            "track_id": track_resp.data[0]["id"],
            "position": pos,
            "added_by": added_by,
        }).execute()

        invalidate(CacheType.USER_PLAYLISTS, suffix=added_by)
        invalidate(CacheType.USER_PLAYLISTS, suffix=f"{playlist_id}:{added_by}")
        
        return {"ok": True, "track": track_resp.data[0], "link": link_resp.data[0]}
    except Exception as e:
        return {"error": "db_error", "detail": str(e)}

@router.delete("/{playlist_id}/tracks/{track_id}")
async def remove_track_from_playlist(request: Request, playlist_id: str, track_id: str):
    jwt = request.headers.get("Authorization", "").replace("Bearer ", "")
    db = db_as_user(jwt)

    try:
        db.table("playlist_tracks") \
            .delete().eq("playlist_id", playlist_id).eq("track_id", track_id).execute()

        owner_id = _get_user_id(request)
        if owner_id:
            invalidate(CacheType.USER_PLAYLISTS, suffix=owner_id)
            invalidate(CacheType.USER_PLAYLISTS, suffix=f"{playlist_id}:{owner_id}")

        return {"ok": True}
    except Exception as e:
        return {"error": "db_error", "detail": str(e)}
    
@router.delete("/{playlist_id}")
async def delete_playlist(request: Request, playlist_id: str):
    jwt = request.headers.get("Authorization", "").replace("Bearer ", "")
    db = db_as_user(jwt)

    owner_id = _get_user_id(request)
    if not owner_id:
        return {"error": "unauthorized"}

    try:
        db.table("playlist_tracks").delete().eq("playlist_id", playlist_id).execute()
        resp = db.table("playlists").delete().eq("id", playlist_id).eq("owner_id", owner_id).execute()

        invalidate(CacheType.USER_PLAYLISTS, suffix=owner_id)
        invalidate(CacheType.USER_PLAYLISTS, suffix=f"{playlist_id}:{owner_id}")

        return {"ok": True, "deleted": resp.data or []}
    except Exception as e:
        return {"error": "db_error", "detail": str(e)}