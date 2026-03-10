from __future__ import annotations
from datetime import datetime, timezone

from services.db_protocol import DBClient

MAX_RECENTS = 30
VALID_ENTITY_TYPES = ("album", "artist", "playlist")

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _validate_entity_type(entity_type: str) -> str | None:
    """Retorna mensaje de error o None si válido."""
    if entity_type not in VALID_ENTITY_TYPES:
        return f"invalid entity_type: {entity_type}"
    return None

def _ids_to_trim(rows: list, max_recents: int = MAX_RECENTS) -> list:
    """Dados rows ordenados por fecha desc, retorna ids a borrar."""
    if len(rows) <= max_recents:
        return []
    return [r["id"] for r in rows[max_recents:]]

def _build_play_event(user_id: str, track_id: str, metadata: dict | None) -> dict:
    return {"user_id": user_id, "track_id": track_id, "metadata": metadata or {}}

def _build_recent_row(user_id: str, entity_type: str, entity_id: str, metadata: dict | None, played_at: str) -> dict:
    return {
        "user_id": user_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "metadata": metadata or {},
        "played_at": played_at,
    }

# ── IO ───────────────────────────────────────────────────
def log_play(db: DBClient, *, user_id: str, track_id: str, metadata: dict | None = None) -> dict:
    """INSERT en play_events."""
    try:
        resp = db.table("play_events").insert(_build_play_event(user_id, track_id, metadata)).execute()
        row = (resp.data or [{}])[0]
        return {"ok": True, "id": row.get("id")}
    except Exception as e:
        print(f"[play_event][ERROR] {e}")
        return {"ok": False, "error": str(e)}

def _trim_recents(db: DBClient, user_id: str) -> None:
    """Borra recents más allá del límite."""
    try:
        rows = (
            db.table("recent_activity")
            .select("id, played_at")
            .eq("user_id", user_id)
            .order("played_at", desc=True)
            .execute()
        ).data or []
        ids = _ids_to_trim(rows)
        if ids:
            db.table("recent_activity").delete().in_("id", ids).execute()
    except Exception as e:
        print(f"[recent][trim][ERROR] {e}")

def upsert_recent(db: DBClient, *, user_id: str, entity_type: str, entity_id: str, metadata: dict | None = None) -> dict:
    """UPSERT en recent_activity + trim."""
    error = _validate_entity_type(entity_type)
    if error:
        return {"ok": False, "error": error}
    try:
        row_data = _build_recent_row(user_id, entity_type, entity_id, metadata, _utc_now_iso())
        resp = db.table("recent_activity").upsert(row_data, on_conflict="user_id,entity_type,entity_id").execute()
        row = (resp.data or [{}])[0]
        _trim_recents(db, user_id)
        return {"ok": True, "id": row.get("id")}
    except Exception as e:
        print(f"[recent][ERROR] {e}")
        return {"ok": False, "error": str(e)}

def get_recents(db: DBClient, *, user_id: str, limit: int = 25) -> list:
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