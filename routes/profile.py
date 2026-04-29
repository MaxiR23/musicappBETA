"""Endpoints de profile del usuario actual."""
from fastapi import APIRouter, Depends
from core.dependencies import get_current_profile, get_user_db
from services.db_protocol import DBClient
from services.profile_service import update_profile
from models.profile import Profile, ProfileUpdate

router = APIRouter()

@router.get("/me", response_model=Profile)
def get_me(profile: Profile = Depends(get_current_profile)):
    """Devuelve el profile del usuario autenticado."""
    return profile

@router.patch("/me", response_model=Profile)
def patch_me(
    update: ProfileUpdate,
    profile: Profile = Depends(get_current_profile),
    db: DBClient = Depends(get_user_db),
):
    """Actualiza campos editables del profile (no incluye role)."""
    return update_profile(db, profile.id, update)