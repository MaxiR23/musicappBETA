from __future__ import annotations

from services.db_protocol import DBClient

def get_all_user_ids(db: DBClient) -> list[str]:
    """
    Devuelve todos los UUIDs de users registrados en auth.users.
    Usa el Auth Admin API de Supabase, que requiere service role.
    El parametro `db` debe ser un cliente inicializado con SERVICE_ROLE_KEY.
    """
    res = db.auth.admin.list_users()
    return [u.id for u in res if u.id]