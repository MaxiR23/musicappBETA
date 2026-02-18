# services/activity_repo.py
from __future__ import annotations
from typing import Any, Dict, List, TypedDict
from services.supabase_service import supabase_service as sb


class RecentSeeds(TypedDict):
    artists: List[Dict[str, Any]]
    albums: List[Dict[str, Any]]


def recent_seeds_from_activity(
    user_id: str,
    per_type: int = 2,
    lookback: int = 400,  # ignorado, mantenido por compatibilidad
) -> RecentSeeds:
    """
    Devuelve los top 'per_type' artists/albums de user_weekly_stats.
    Lee de la semana más reciente disponible.
    """
    # Obtener stats de artist y album de las últimas semanas
    # Limit 4 para cubrir 2 semanas * 2 entity_types
    response = (
        sb.table("user_weekly_stats")
          .select("entity_type, stats, week_start")
          .eq("user_id", user_id)
          .in_("entity_type", ["artist", "album"])
          .order("week_start", desc=True)
          .limit(4)
          .execute()
    )
    
    rows: List[Dict[str, Any]] = getattr(response, "data", None) or []
    
    out: RecentSeeds = {"artists": [], "albums": []}
    
    if not rows:
        return out
    
    # Obtener la semana más reciente
    latest_week = rows[0].get("week_start")
    
    for row in rows:
        # Solo procesar la semana más reciente
        if row.get("week_start") != latest_week:
            continue
            
        entity_type = row.get("entity_type")
        stats = row.get("stats") or []
        
        for item in stats[:per_type]:
            entity_id = item.get("entity_id")
            if not entity_id:
                continue
            
            seed = {
                "id": entity_id,
                "entity_type": entity_type,
                "metadata": {
                    "display_name": item.get("display_name"),
                    "thumbnail_url": item.get("thumbnail_url"),
                },
            }
            
            # Agregar metadata extra para albums
            if entity_type == "album":
                seed["metadata"]["artist_id"] = item.get("artist_id")
                seed["metadata"]["artist_name"] = item.get("artist_name")
            
            if entity_type == "artist":
                out["artists"].append(seed)
            elif entity_type == "album":
                out["albums"].append(seed)
    
    return out