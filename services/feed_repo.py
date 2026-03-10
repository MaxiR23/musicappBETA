# services/feed_repo.py
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Tuple

from services.supabase_service import supabase_service as sb

TABLE = "feed_current"

def _to_int(v: Any) -> int | None:
    try:
        if v is None or v == "":
            return None
        return int(v)
    except Exception:
        return None

def _row_from_album(kind: str, a: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "kind":        kind,
        "type":        "album",
        "id":          a.get("id"),
        "title":       a.get("title"),
        "artist":      a.get("artist"),
        "artist_id":   a.get("artist_id"),
        "album":       None,
        "album_id":    None,
        "thumb":       a.get("thumbnail"),
        "url":         f"/browse/{a.get('id')}" if a.get("id") else None,
        "year":        _to_int(a.get("year")),
        "release_date": a.get("release_date"),
        "duration_seconds": None,
    }

def _row_from_track(kind: str, t: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "kind":        kind,
        "type":        "track",
        "id":          t.get("id"),
        "title":       t.get("title"),
        "artist":      t.get("artist"),
        "artist_id":   t.get("artist_id"),
        "thumb":       t.get("thumbnail_url"),
        "url":         f"/watch/{t.get('id')}" if t.get("id") else None,
        "album":       t.get("album"),
        "album_id":    t.get("album_id"),
        "duration_seconds": _to_int(t.get("duration_seconds")),
        "year":        None,
        "release_date": t.get("release_date"),
    }

def replace_feed(kind: str, media_type: str, items: Iterable[Dict[str, Any]]) -> Tuple[int | None, int]:
    # 1) DELETE
    try:
        del_res = sb.table(TABLE).delete().eq("kind", kind).eq("type", media_type).execute()
        deleted = getattr(del_res, "count", None) or None
    except Exception as e:
        print(f"Warning: DELETE falló: {e}")
        deleted = None

    # 2) Preparar rows
    if media_type == "album":
        rows: List[Dict[str, Any]] = [_row_from_album(kind, it) for it in items]
    else:
        rows = [_row_from_track(kind, it) for it in items]

    # 3) DEDUPLICAR por ID
    rows_by_id: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        row_id = r.get("id")
        if row_id:
            rows_by_id[row_id] = r
    
    unique_rows = list(rows_by_id.values())
    
    print(f"[feed_repo] {kind}/{media_type}: {len(rows)} items → {len(unique_rows)} únicos")
    
    # 4) UPSERT
    try:
        if unique_rows:
            sb.table(TABLE).upsert(
                unique_rows,
                on_conflict="kind,type,id"
            ).execute()
    except Exception as e:
        print(f"[feed_repo][UPSERT][ERROR] {kind}/{media_type}: {e}")
        return deleted, 0

    return deleted, len(unique_rows)

def list_feed(kind: str, media_type: str, limit: int = 25) -> List[Dict[str, Any]]:
    try:
        q = sb.table(TABLE).select("*").eq("kind", kind).eq("type", media_type)
        if media_type == "album" and kind == "new_releases":
            q = q.order("release_date", desc=True)
        else:
            q = q.order("id", desc=False)
        q = q.limit(limit)
        res = q.execute()
        return (getattr(res, "data", None) or [])
    except Exception as e:
        print(f"[feed_repo][list_feed][ERROR] {kind}/{media_type}: {e}")
        return []

def list_new_releases_for_artist(artist_id: str, limit: int = 8) -> List[Dict[str, Any]]:
    try:
        q = sb.table(TABLE).select("*") \
            .eq("kind", "new_releases") \
            .eq("type", "album") \
            .eq("artist_id", artist_id) \
            .order("release_date", desc=True) \
            .limit(limit)
        res = q.execute()
        return getattr(res, "data", None) or []
    except Exception as e:
        print(f"[feed_repo][new_releases_for_artist][ERROR] {artist_id}: {e}")
        return []