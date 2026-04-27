from __future__ import annotations
from typing import Any, Dict, Iterable, List, Tuple

from services.db_protocol import DBClient

TABLE = "feed_current"

def _to_int(v: Any) -> int | None:
    try:
        if v is None or v == "":
            return None
        return int(v)
    except Exception:
        return None

def _compact(row: Dict[str, Any]) -> Dict[str, Any]:
    """Saca campos None del row."""
    return {k: v for k, v in row.items() if v is not None}

def _row_from_album(kind: str, a: Dict[str, Any]) -> Dict[str, Any]:
    return _compact({
        "kind":        kind,
        "type":        "album",
        "id":          a.get("id"),
        "title":       a.get("title"),
        "artists":     a.get("artists") or [],
        "thumb":       a.get("thumbnail"),
        "year":        _to_int(a.get("year")) and str(_to_int(a.get("year"))),
        "release_date": a.get("release_date"),
    })

def _row_from_track(kind: str, t: Dict[str, Any]) -> Dict[str, Any]:
    return _compact({
        "kind":        kind,
        "type":        "track",
        "id":          t.get("id"),
        "title":       t.get("title"),
        "artists":     t.get("artists") or [],
        "thumb":       t.get("thumbnail_url"),
        "album":       t.get("album"),
        "album_id":    t.get("album_id"),
        "duration_seconds": _to_int(t.get("duration_seconds")),
        "release_date": t.get("release_date"),
    })

def build_rows(kind: str, media_type: str, items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Construye rows desde items según media_type."""
    mapper = _row_from_album if media_type == "album" else _row_from_track
    return [mapper(kind, it) for it in items]

def dedupe_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplica rows por id, mantiene el último."""
    rows_by_id: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        row_id = r.get("id")
        if row_id:
            rows_by_id[row_id] = r
    return list(rows_by_id.values())

# ── IO ───────────────────────────────────────────────────
def replace_feed(db: DBClient, kind: str, media_type: str, items: Iterable[Dict[str, Any]]) -> Tuple[int | None, int]:
    """Reemplaza feed: DELETE + UPSERT."""
    try:
        del_res = db.table(TABLE).delete().eq("kind", kind).eq("type", media_type).execute()
        deleted = getattr(del_res, "count", None) or None
    except Exception as e:
        print(f"Warning: DELETE falló: {e}")
        deleted = None

    rows = build_rows(kind, media_type, items)
    unique_rows = dedupe_rows(rows)
    print(f"[feed_repo] {kind}/{media_type}: {len(rows)} items -> {len(unique_rows)} únicos")

    if not unique_rows:
        return deleted, 0
    try:
        db.table(TABLE).upsert(unique_rows, on_conflict="kind,type,id").execute()
        return deleted, len(unique_rows)
    except Exception as e:
        print(f"[feed_repo][UPSERT][ERROR] {kind}/{media_type}: {e}")
        return deleted, 0

def list_feed(db: DBClient, kind: str, media_type: str, limit: int = 25) -> List[Dict[str, Any]]:
    """Lista items del feed."""
    try:
        q = db.table(TABLE).select("*").eq("kind", kind).eq("type", media_type)
        if media_type == "album" and kind == "new_releases":
            q = q.order("release_date", desc=True)
        else:
            q = q.order("id", desc=False)
        res = q.limit(limit).execute()
        rows = getattr(res, "data", None) or []
        return [_compact(r) for r in rows]
    except Exception as e:
        print(f"[feed_repo][list_feed][ERROR] {kind}/{media_type}: {e}")
        return []