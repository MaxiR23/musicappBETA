# services/activity_repo.py
from __future__ import annotations
from typing import Any, Dict, List, Literal, TypedDict
from services.supabase_service import supabase_service as sb

EntityType = Literal["artist", "album"]

class RecentSeeds(TypedDict):
    artists: List[Dict[str, Any]]
    albums: List[Dict[str, Any]]

def recent_seeds_from_activity(
    user_id: str,
    per_type: int = 2,
    lookback: int = 400,
) -> RecentSeeds:
    """
    Devuelve los últimos 'per_type' únicos por tipo (artists/albums)
    según occurred_at DESC. NO filtra por event_type.
    """
    res = (
        sb.table("user_activity")
          .select("entity_type,entity_id,context_type,context_id,metadata,occurred_at")
          .eq("user_id", user_id)
          .in_("entity_type", ["artist", "album"])
          .order("occurred_at", desc=True)
          .limit(lookback)
          .execute()
    )
    rows: List[Dict[str, Any]] = getattr(res, "data", None) or []

    seen = {"artist": set(), "album": set()}
    out: RecentSeeds = {"artists": [], "albums": []}

    for r in rows:
        et = r.get("entity_type")
        eid = r.get("entity_id")
        if et not in ("artist", "album") or not eid:
            continue
        if eid in seen[et]:
            continue

        item = {
            "id": eid,
            "entity_type": et,
            "context_type": r.get("context_type"),
            "context_id": r.get("context_id"),
            "metadata": r.get("metadata") or {},
            "occurred_at": r.get("occurred_at"),
        }

        if et == "artist" and len(out["artists"]) < per_type:
            out["artists"].append(item)
            seen["artist"].add(eid)
        elif et == "album" and len(out["albums"]) < per_type:
            out["albums"].append(item)
            seen["album"].add(eid)

        if len(out["artists"]) >= per_type and len(out["albums"]) >= per_type:
            break

    return out