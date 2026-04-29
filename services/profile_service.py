"""Servicio de profiles: operaciones de lectura y actualizacion contra Supabase."""
from __future__ import annotations

from models.profile import Profile, ProfileUpdate
from services.db_protocol import DBClient

def get_profile_by_id(db: DBClient, user_id: str) -> Profile | None:
    """Obtiene un profile por id. Devuelve None si no existe."""
    response = (
        db.table("profiles")
        .select("*")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    if not response.data:
        return None
    return Profile(**response.data)

def update_profile(db: DBClient, user_id: str, update: ProfileUpdate) -> Profile:
    """Actualiza campos editables del profile. No permite cambiar role."""
    payload = update.model_dump(exclude_none=True)

    if not payload:
        existing = get_profile_by_id(db, user_id)
        if not existing:
            raise ValueError(f"Profile not found: {user_id}")
        return existing

    response = (
        db.table("profiles")
        .update(payload)
        .eq("id", user_id)
        .execute()
    )
    if not response.data:
        raise ValueError(f"Profile not found or update failed: {user_id}")
    return Profile(**response.data[0])