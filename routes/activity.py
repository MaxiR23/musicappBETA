"""Endpoints de actividad: plays y recent"""
from fastapi import APIRouter, Path, Body, Request, Depends

from core.dependencies import get_db, get_current_user_id
from services.db_protocol import DBClient
from services.activity_service import log_play, upsert_recent, get_recents
from services.track_service import ensure_duration_seconds

router = APIRouter()

# ── HELPERS ──────────────────────────────────────────────
def _extract_display_meta(body: dict) -> dict:
    """Extrae display_name y thumbnail_url del body."""
    meta = {}
    dn = body.get("display_name") or body.get("name") or body.get("title")
    th = body.get("thumbnail_url") or body.get("thumbnail")
    if dn:
        meta["display_name"] = dn
    if th:
        meta["thumbnail_url"] = th
    return meta

# ── PLAYS ────────────────────────────────────────────────
@router.post("/plays/tracks/{track_id}")
def log_play_track(
    track_id: str = Path(...),
    body: dict | None = Body(None),
    db: DBClient = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Play real (30+ seg) → INSERT en play_events."""
    b = body or {}
    metadata = {}
    if b.get("album_id"): metadata["album_id"] = b["album_id"]
    if b.get("album_name"): metadata["album_name"] = b["album_name"]
    if b.get("artist_id"): metadata["artist_id"] = b["artist_id"]
    if b.get("track_name"): metadata["track_name"] = b["track_name"]
    if b.get("artist_name"): metadata["artist_name"] = b["artist_name"]
    if b.get("thumbnail_url"): metadata["thumbnail_url"] = b["thumbnail_url"]
    metadata["duration_seconds"] = ensure_duration_seconds(track_id, b.get("duration_seconds"))

    result = log_play(db, user_id=user_id, track_id=track_id, metadata=metadata)
    return {"ok": result.get("ok", False)}

@router.post("/plays/albums/{album_id}")
def log_play_album(
    album_id: str = Path(...),
    body: dict | None = Body(None),
    db: DBClient = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Usuario reproduce desde un album → UPSERT en recent_activity."""
    meta = _extract_display_meta(body or {})
    upsert_recent(db, user_id=user_id, entity_type="album", entity_id=album_id, metadata=meta)
    return {"ok": True}

@router.post("/plays/artists/{artist_id}")
def log_play_artist(
    artist_id: str = Path(...),
    body: dict | None = Body(None),
    db: DBClient = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Usuario reproduce desde un artista → UPSERT en recent_activity."""
    meta = _extract_display_meta(body or {})
    upsert_recent(db, user_id=user_id, entity_type="artist", entity_id=artist_id, metadata=meta)
    return {"ok": True}

@router.post("/plays/playlists/{playlist_id}")
def log_play_playlist(
    playlist_id: str = Path(...),
    body: dict | None = Body(None),
    db: DBClient = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Usuario reproduce desde una playlist → UPSERT en recent_activity."""
    meta = _extract_display_meta(body or {})
    upsert_recent(db, user_id=user_id, entity_type="playlist", entity_id=playlist_id, metadata=meta)
    return {"ok": True}

# ── RECENT ───────────────────────────────────────────────
@router.get("/me/recent")
def get_recent(
    limit: int = 30,
    db: DBClient = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    """Recently Played → lee de recent_activity."""
    items = get_recents(db, user_id=user_id, limit=limit)
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