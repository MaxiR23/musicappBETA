# services/activity_service.py
from __future__ import annotations
from typing import Any, Optional, Dict
from datetime import datetime, timezone

from services.supabase_service import db_as_user
from services.jwt_utils import decode_jwt

MAX_RECENTS = 30

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _get_user_id_from_request(request) -> Optional[str]:
    user = getattr(request.state, "user", None)
    if isinstance(user, dict) and user.get("id"):
        return user["id"]
    token = (request.headers.get("Authorization") or "").replace("Bearer ", "")
    if not token:
        return None
    claims = decode_jwt(token) or {}
    return claims.get("sub") or claims.get("user_id")

def _db_for_request(request):
    jwt = (request.headers.get("Authorization") or "").replace("Bearer ", "")
    return db_as_user(jwt)


# ── PLAY EVENTS ──────────────────────────────────────────

def log_play(db, *, user_id: str, track_id: str, metadata: dict = None) -> dict:
    """INSERT en play_events. Un row por cada play real (30+ seg)."""
    try:
        resp = db.table("play_events").insert({
            "user_id": user_id,
            "track_id": track_id,
            "metadata": metadata or {},
        }).execute()
        row = (resp.data or [{}])[0]
        print(f"[play_event] OK id={row.get('id')}")
        return {"ok": True, "id": row.get("id")}
    except Exception as e:
        print(f"[play_event][ERROR] {e}")
        return {"ok": False, "error": str(e)}

# ── RECENT ACTIVITY ──────────────────────────────────────

def upsert_recent(db, *, user_id: str, entity_type: str, entity_id: str, metadata: dict = None) -> dict:
    """
    UPSERT en recent_activity. Si ya existe (user, type, id) → actualiza played_at.
    Después recorta a MAX_RECENTS.
    """
    if entity_type not in ("album", "artist", "playlist"):
        return {"ok": False, "error": f"invalid entity_type: {entity_type}"}

    now = _utc_now_iso()
    try:
        # UPSERT via ON CONFLICT (unique constraint)
        resp = db.table("recent_activity").upsert({
            "user_id": user_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "metadata": metadata or {},
            "played_at": now,
        }, on_conflict="user_id,entity_type,entity_id").execute()

        row = (resp.data or [{}])[0]
        print(f"[recent] UPSERT OK {entity_type}={entity_id}")

        # Recortar: borrar los más viejos si hay más de MAX_RECENTS
        _trim_recents(db, user_id)

        return {"ok": True, "id": row.get("id")}
    except Exception as e:
        print(f"[recent][ERROR] {e}")
        return {"ok": False, "error": str(e)}


def _trim_recents(db, user_id: str):
    """Borra recents más allá del límite de MAX_RECENTS."""
    try:
        all_rows = (
            db.table("recent_activity")
            .select("id, played_at")
            .eq("user_id", user_id)
            .order("played_at", desc=True)
            .execute()
        ).data or []

        if len(all_rows) > MAX_RECENTS:
            ids_to_delete = [r["id"] for r in all_rows[MAX_RECENTS:]]
            db.table("recent_activity").delete().in_("id", ids_to_delete).execute()
            print(f"[recent] trimmed {len(ids_to_delete)} old recents")
    except Exception as e:
        print(f"[recent][trim][ERROR] {e}")


def get_recents(db, *, user_id: str, limit: int = 25) -> list:
    """Lee recent_activity ordenado por played_at DESC."""
    try:
        resp = (
            db.table("recent_activity")
            .select("entity_type, entity_id, metadata, played_at")
            .eq("user_id", user_id)
            .order("played_at", desc=True)
            .limit(min(limit, MAX_RECENTS))
            .execute()
        )
        return resp.data or []
    except Exception as e:
        print(f"[recent][get][ERROR] {e}")
        return []


# ── CONVENIENCE (desde request) ──────────────────────────

def log_play_from_request(request, *, track_id: str, metadata: dict = None) -> dict:
    user_id = _get_user_id_from_request(request)
    if not user_id:
        return {"ok": False, "error": "unauthorized"}
    db = _db_for_request(request)
    return log_play(db, user_id=user_id, track_id=track_id, metadata=metadata)


def upsert_recent_from_request(request, *, entity_type: str, entity_id: str, metadata: dict = None) -> dict:
    user_id = _get_user_id_from_request(request)
    if not user_id:
        return {"ok": False, "error": "unauthorized"}
    db = _db_for_request(request)
    return upsert_recent(db, user_id=user_id, entity_type=entity_type, entity_id=entity_id, metadata=metadata)


def get_recents_from_request(request, limit: int = 25) -> list:
    user_id = _get_user_id_from_request(request)
    if not user_id:
        return []
    db = _db_for_request(request)
    return get_recents(db, user_id=user_id, limit=limit)