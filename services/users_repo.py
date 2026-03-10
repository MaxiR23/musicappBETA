from __future__ import annotations

from services.db_protocol import DBClient

def get_all_user_ids(db: DBClient) -> list:
    """Obtiene todos los UUIDs de la tabla user_ids."""
    res = db.table("user_ids").select("id").execute()
    data = getattr(res, "data", None) or []
    return [row["id"] for row in data if row.get("id")]