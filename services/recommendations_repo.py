# services/recommendations_repo.py
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional, TypedDict, Literal
from datetime import datetime
from services.supabase_service import supabase_service as sb

ItemType = Literal["artist", "album", "playlist"]  # playlist opcional si tu enum lo soporta
class SeedInfo(TypedDict, total=False):
    seed_type: ItemType
    seed_id: str
    seed_name: Optional[str]
    seed_thumb: Optional[str]
class RecommendationItem(TypedDict, total=False):
    """
    Item genérico para persistir en public.user_recommendations
    - rank: si no viene, lo asignamos secuencialmente 1..N
    - payload: libre (name/title/subtitle/thumbnails/artist_name/track_count/etc.)
    - source: etiqueta del algoritmo (ej. 'seed_recos_v1')
    - valid_until: ISO-8601 string o datetime opcional
    """
    item_type: ItemType
    item_id: str
    rank: Optional[int]
    payload: Dict[str, Any]
    source: Optional[str]
    valid_until: Optional[str]  # ISO-8601 o None
    # “Similar to …”
    seed_type: Optional[ItemType]
    seed_id: Optional[str]
    seed_name: Optional[str]
    seed_thumb: Optional[str]

def _to_iso(dt: Any) -> Optional[str]:
    if not dt:
        return None
    if isinstance(dt, str):
        return dt
    if isinstance(dt, datetime):
        return dt.isoformat()
    return None

def _row(
    user_id: str,
    bucket: str,
    it: RecommendationItem,
    fallback_rank: int,
) -> Dict[str, Any]:
    # rank: si no viene, usar contador (1..N)
    rank = int(it.get("rank") or fallback_rank)

    # payload nunca null
    payload = it.get("payload") or {}

    row = {
        "user_id":     user_id,
        "bucket":      bucket,
        "item_type":   it["item_type"],
        "item_id":     it["item_id"],
        "rank":        rank,
        "payload":     payload,
        "source":      it.get("source"),
        "valid_until": _to_iso(it.get("valid_until")),
        # similar to ...
        "seed_type":   it.get("seed_type"),
        "seed_id":     it.get("seed_id"),
        "seed_name":   it.get("seed_name"),
        "seed_thumb":  it.get("seed_thumb"),
    }
    return row

def replace_user_recommendations(
    user_id: str,
    bucket: str,
    items: Iterable[RecommendationItem],
) -> Dict[str, Any]:
    """
    Reemplaza COMPLETAMENTE (delete + insert) el bucket de recomendaciones
    para (user_id, bucket). Idempotente y DRY.

    - Respeta rank si viene; asigna 1..N si no.
    - Requiere que 'item_type' y 'item_id' vengan en cada item.
    - Usa la tabla: public.user_recommendations
    """
    items_list = [it for it in items if it and it.get("item_type") and it.get("item_id")]
    if not items_list:
        # vacío → borra y devuelve 0 insertados
        try:
            sb.table("user_recommendations").delete().eq("user_id", user_id).eq("bucket", bucket).execute()
        except Exception:
            pass
        return {"deleted": None, "inserted": 0}

    # 1) borrar bucket anterior
    try:
        del_res = (
            sb.table("user_recommendations")
              .delete()
              .eq("user_id", user_id)
              .eq("bucket", bucket)
              .execute()
        )
        deleted = getattr(del_res, "count", None) or None
    except Exception:
        deleted = None

    # 2) normalizar y rankear
    rows: List[Dict[str, Any]] = []
    next_rank = 1
    # si hay items que ya traen rank, los usamos; luego completamos “huecos” con next_rank
    # para mantener orden estable, evaluamos primero los que traen rank explícito ordenados,
    # luego los que no traen rank en el orden recibido.
    with_rank = [it for it in items_list if it.get("rank") is not None]
    without_rank = [it for it in items_list if it.get("rank") is None]

    # ordenar por rank asc los que lo traen
    try:
        with_rank.sort(key=lambda x: int(x.get("rank") or 0))
    except Exception:
        pass

    for it in with_rank + without_rank:
        r = _row(user_id, bucket, it, fallback_rank=next_rank)
        rows.append(r)
        # si el ítem tenía rank, respetamos; si no, asignamos y avanzamos
        next_rank = max(next_rank + 1, (int(it.get("rank") or 0) + 1))

    # 3) insertar
    if rows:
        sb.table("user_recommendations").insert(rows).execute()

    return {"deleted": deleted, "inserted": len(rows)}

def list_user_recommendations(
    user_id: str,
    bucket: str,
    item_type: Optional[str] = None,  # 'artist' | 'album' | None
    limit: int = 100,
) -> List[Dict[str, Any]]:
    q = (
        sb.table("user_recommendations")
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