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
    # mapea a tus columnas reales (lowercase)
    return {
        "kind":        kind,               # 'most_played' | 'new_releases'
        "type":        "album",
        "id":          a.get("id"),
        "title":       a.get("title"),
        "artist":      a.get("artist"),
        "thumb":       a.get("thumb"),
        "url":         a.get("url"),
        "year":        _to_int(a.get("year")),          # int4
        "track_count":  _to_int(a.get("track_count")),    # int4
        "release_date": a.get("release_date"),            # text  
        "artist_id":   a.get("artist_id") or a.get("artistId"),
        # campos de track -> null
        "album":       None,
        "duration":    None,
        "duration_s":  None,
    }

def _row_from_track(kind: str, t: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "kind":        kind,
        "type":        "track",
        "id":          t.get("id"),
        "title":       t.get("title"),
        "artist":      t.get("artist"),
        "thumb":       t.get("thumb"),
        "url":         t.get("url"),
        "artist_id":   t.get("artist_id") or t.get("artistId"),
        "album":       t.get("album"),
        "duration":    t.get("duration"),
        "duration_s":  _to_int(t.get("duration_s")),    # int4
        # solo álbum -> null
        "year":        None,
        "track_count":  None,
        # new-releases solo aplica a álbumes; por las dudas lo respetamos si viene
        "release_date": t.get("release_date"),
    }

def replace_feed(kind: str, media_type: str, items: Iterable[Dict[str, Any]]) -> Tuple[int | None, int]:
    """
    Reemplaza TODO el contenido actual de feed_current para (kind, media_type)
    por 'items' (ya mapeados). Devuelve (#deleted | None, #inserted).
    """
    
    # 1) DELETE
    try:
        del_res = sb.table(TABLE).delete().eq("kind", kind).eq("type", media_type).execute()
        deleted = getattr(del_res, "count", None) or None
    except Exception as e:
        print(f"⚠️ Warning: DELETE falló: {e}")
        deleted = None

    # 2) Preparar rows
    if media_type == "album":
        rows: List[Dict[str, Any]] = [_row_from_album(kind, it) for it in items]
    else:
        rows = [_row_from_track(kind, it) for it in items]

    # 3) ✅ DEDUPLICAR por ID antes de insertar (último gana)
    rows_by_id: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        row_id = r.get("id")
        if row_id:
            rows_by_id[row_id] = r
    
    unique_rows = list(rows_by_id.values())
    
    print(f"[feed_repo] {kind}/{media_type}: {len(rows)} items → {len(unique_rows)} únicos")
    
    # 4) UPSERT
    if unique_rows:
        sb.table(TABLE).upsert(
            unique_rows,
            on_conflict="kind,type,id"
        ).execute()

    return deleted, len(unique_rows)

def list_feed(kind: str, media_type: str, limit: int = 25) -> List[Dict[str, Any]]:
    q = sb.table(TABLE).select("*").eq("kind", kind).eq("type", media_type)
    # Para new_releases (álbumes) ordenamos por fecha de lanzamiento desc
    if media_type == "album" and kind == "new_releases":
        q = q.order("release_date", desc=True)
    else:
        q = q.order("id", desc=False)
    q = q.limit(limit)
    res = q.execute()
    return (getattr(res, "data", None) or [])  # filas ya tienen el shape que espera el front

def list_new_releases_for_artist(artist_id: str, limit: int = 8) -> List[Dict[str, Any]]:
    q = sb.table(TABLE).select("*") \
        .eq("kind", "new_releases") \
        .eq("type", "album") \
        .eq("artist_id", artist_id) \
        .order("release_date", desc=True) \
        .limit(limit)
    res = q.execute()
    return getattr(res, "data", None) or []