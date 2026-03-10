from __future__ import annotations
from typing import Any, Dict, List, Optional, TypedDict
from services.db_protocol import DBClient
class RecentSeeds(TypedDict):
    artists: List[Dict[str, Any]]
    albums: List[Dict[str, Any]]

def _build_seed(item: Dict[str, Any], entity_type: str) -> Optional[Dict[str, Any]]:
    """Construye un seed individual."""
    entity_id = item.get("entity_id")
    if not entity_id:
        return None

    seed = {
        "id": entity_id,
        "entity_type": entity_type,
        "metadata": {
            "display_name": item.get("display_name"),
            "thumbnail_url": item.get("thumbnail_url"),
        },
    }

    if entity_type == "album":
        seed["metadata"]["artist_id"] = item.get("artist_id")
        seed["metadata"]["artist_name"] = item.get("artist_name")

    return seed

def _extract_seeds(rows: List[Dict[str, Any]], per_type: int) -> RecentSeeds:
    """Lógica pura: extrae seeds de rows (sin IO)."""
    out: RecentSeeds = {"artists": [], "albums": []}

    if not rows:
        return out

    latest_week = rows[0].get("week_start")

    for row in rows:
        if row.get("week_start") != latest_week:
            continue

        entity_type = row.get("entity_type")
        stats = row.get("stats") or []

        for item in stats[:per_type]:
            seed = _build_seed(item, entity_type)
            if seed:
                key = "artists" if entity_type == "artist" else "albums"
                out[key].append(seed)

    return out

def recent_seeds_from_activity(
    db: DBClient,
    user_id: str,
    per_type: int = 2,
) -> RecentSeeds:
    """
    Devuelve los top 'per_type' artists/albums de user_weekly_stats.
    Lee de la semana más reciente disponible.
    """
    response = (
        db.table("user_weekly_stats")
        .select("entity_type, stats, week_start")
        .eq("user_id", user_id)
        .in_("entity_type", ["artist", "album"])
        .order("week_start", desc=True)
        .limit(4)
        .execute()
    )

    rows: List[Dict[str, Any]] = getattr(response, "data", None) or []
    return _extract_seeds(rows, per_type)