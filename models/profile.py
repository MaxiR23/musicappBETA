"""INFO: Modelos de Profile: representan filas de la tabla public.profiles."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

Role = Literal["admin", "developer", "tester", "user"]

ROLE_HIERARCHY: dict[str, int] = {
    "user": 0,
    "tester": 1,
    "developer": 2,
    "admin": 3,
}

class Profile(BaseModel):
    """Representa una fila de la tabla public.profiles."""
    id: str
    username: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    role: Role = "user"
    created_at: str
    updated_at: str

class ProfileUpdate(BaseModel):
    """Payload para actualizar un profile. No incluye role a proposito."""
    username: str | None = Field(default=None, min_length=3, max_length=30)
    display_name: str | None = Field(default=None, min_length=1, max_length=50)
    avatar_url: str | None = None

def has_role_or_higher(user_role: str, required_role: str) -> bool:
    """Compara roles segun la jerarquia: admin > developer > tester > user."""
    user_level = ROLE_HIERARCHY.get(user_role, -1)
    required_level = ROLE_HIERARCHY.get(required_role, -1)
    return user_level >= required_level