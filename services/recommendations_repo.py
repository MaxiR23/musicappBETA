from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional, TypedDict, Literal
from datetime import datetime

from services.db_protocol import DBClient

ItemType = Literal["artist", "album", "playlist"]
class SeedInfo(TypedDict, total=False):
    seed_type: ItemType
    seed_id: str
    seed_name: Optional[str]
    seed_thumb: Optional[str]
class RecommendationItem(TypedDict, total=False):
    item_type: ItemType
    item_id: str
    rank: Optional[int]
    payload: Dict[str, Any]
    source: Optional[str]
    valid_until: Optional[str]
    seed_type: Optional[ItemType]
    seed_id: Optional[str]
    seed_name: Optional[str]
    seed_thumb: Optional[str]

def _to_iso(dt) -> str | None:
    if not dt:
        return None
    if isinstance(dt, str):
        return dt
    if isinstance(dt, datetime):
        return dt.isoformat()
    return None

def _build_row(user_id: str, bucket: str, it: RecommendationItem, fallback_rank: int) -> dict:
    return {
        "user_id":     user_id,
        "bucket":      bucket,
        "item_type":   it["item_type"],
        "item_id":     it["item_id"],
        "rank":        int(it.get("rank") or fallback_rank),
        "payload":     it.get("payload") or {},
        "source":      it.get("source"),
        "valid_until": _to_iso(it.get("valid_until")),
        "seed_type":   it.get("seed_type"),
        "seed_id":     it.get("seed_id"),
        "seed_name":   it.get("seed_name"),
        "seed_thumb":  it.get("seed_thumb"),
    }

def _filter_valid_items(items: Iterable[RecommendationItem]) -> list:
    return [it for it in items if it and it.get("item_type") and it.get("item_id")]

def _split_by_rank(items: list) -> tuple[list, list]:
    with_rank = [it for it in items if it.get("rank") is not None]
    without_rank = [it for it in items if it.get("rank") is None]
    try:
        with_rank.sort(key=lambda x: int(x.get("rank") or 0))
    except Exception:
        pass
    return with_rank, without_rank

def _build_rows(user_id: str, bucket: str, items: list) -> list:
    with_rank, without_rank = _split_by_rank(items)
    rows = []
    next_rank = 1
    for it in with_rank + without_rank:
        rows.append(_build_row(user_id, bucket, it, fallback_rank=next_rank))
        next_rank = max(next_rank + 1, (int(it.get("rank") or 0) + 1))
    return rows

# ── IO ───────────────────────────────────────────────────
def replace_user_recommendations(db: DBClient, user_id: str, bucket: str, items: Iterable[RecommendationItem]) -> dict:
    """Reemplaza COMPLETAMENTE (delete + insert) el bucket de recomendaciones."""
    items_list = _filter_valid_items(items)

    if not items_list:
        try:
            db.table("user_recommendations").delete().eq("user_id", user_id).eq("bucket", bucket).execute()
        except Exception:
            pass
        return {"deleted": None, "inserted": 0}

    try:
        del_res = db.table("user_recommendations").delete().eq("user_id", user_id).eq("bucket", bucket).execute()
        deleted = getattr(del_res, "count", None) or None
    except Exception:
        deleted = None

    rows = _build_rows(user_id, bucket, items_list)

    if rows:
        db.table("user_recommendations").insert(rows).execute()

    return {"deleted": deleted, "inserted": len(rows)}

def list_user_recommendations(db: DBClient, user_id: str, bucket: str, item_type: str | None = None, limit: int = 100) -> list:
    """Lista recomendaciones de un bucket."""
    q = (
        db.table("user_recommendations")
        .select("*")
        .eq("user_id", user_id)
        .eq("bucket", bucket)
        .order("rank", desc=False)
        .limit(max(1, min(limit, 500)))
    )
    if item_type:
        q = q.eq("item_type", item_type)
    res = q.execute()
    return getattr(res, "data", None) or []