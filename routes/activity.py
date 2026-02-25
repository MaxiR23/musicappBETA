# routes/activity.py
"""
Endpoints de actividad: plays y recent
"""
from fastapi import APIRouter, Path, Body, Request
from fastapi.responses import JSONResponse

from services.activity_service import log_play_from_request, upsert_recent_from_request, get_recents_from_request

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════════════
# PLAYS
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/plays/tracks/{track_id}")
def log_play_track(request: Request, track_id: str = Path(...), body: dict | None = Body(None)):
    """Play real (30+ seg) → INSERT en play_events."""
    b = body or {}
    metadata = {}
    if b.get("album_id"): metadata["album_id"] = b["album_id"]
    if b.get("album_name"): metadata["album_name"] = b["album_name"]
    if b.get("artist_id"): metadata["artist_id"] = b["artist_id"]
    if b.get("track_name"): metadata["track_name"] = b["track_name"]
    if b.get("artist_name"): metadata["artist_name"] = b["artist_name"]
    if b.get("thumbnail_url"): metadata["thumbnail_url"] = b["thumbnail_url"]
    
    result = log_play_from_request(request, track_id=track_id, metadata=metadata)
    return {"ok": result.get("ok", False)}


@router.post("/plays/albums/{album_id}")
def log_play_album(request: Request, album_id: str = Path(...), body: dict | None = Body(None)):
    """Usuario reproduce desde un album → UPSERT en recent_activity."""
    b = body or {}
    meta = {}
    dn = b.get("display_name") or b.get("name") or b.get("title")
    th = b.get("thumbnail_url") or b.get("thumbnail")
    if dn: meta["display_name"] = dn
    if th: meta["thumbnail_url"] = th
    upsert_recent_from_request(request, entity_type="album", entity_id=album_id, metadata=meta)
    return {"ok": True}


@router.post("/plays/artists/{artist_id}")
def log_play_artist(request: Request, artist_id: str = Path(...), body: dict | None = Body(None)):
    """Usuario reproduce desde un artista → UPSERT en recent_activity."""
    b = body or {}
    meta = {}
    dn = b.get("display_name") or b.get("name") or b.get("title")
    th = b.get("thumbnail_url") or b.get("thumbnail")
    if dn: meta["display_name"] = dn
    if th: meta["thumbnail_url"] = th
    upsert_recent_from_request(request, entity_type="artist", entity_id=artist_id, metadata=meta)
    return {"ok": True}


@router.post("/plays/playlists/{playlist_id}")
def log_play_playlist(request: Request, playlist_id: str = Path(...), body: dict | None = Body(None)):
    """Usuario reproduce desde una playlist → UPSERT en recent_activity."""
    b = body or {}
    meta = {}
    dn = b.get("display_name") or b.get("name") or b.get("title")
    th = b.get("thumbnail_url") or b.get("thumbnail")
    if dn: meta["display_name"] = dn
    if th: meta["thumbnail_url"] = th
    upsert_recent_from_request(request, entity_type="playlist", entity_id=playlist_id, metadata=meta)
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# RECENT
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/me/recent")
def get_recent(request: Request, limit: int = 25):
    """Recently Played → lee de recent_activity."""
    jwt = (request.headers.get("Authorization") or "").replace("Bearer ", "").strip()
    if not jwt:
        return JSONResponse(status_code=401, content={"ok": False, "error": "unauthorized"})
    
    items = get_recents_from_request(request, limit=limit)
    return {"items": [
        {
            "type": r.get("entity_type"),
            "id": r.get("entity_id"),
            "played_at": r.get("played_at"),
            "name": (r.get("metadata") or {}).get("display_name"),
            "thumbnail_url": (r.get("metadata") or {}).get("thumbnail_url"),
        }
        for r in items
    ]}