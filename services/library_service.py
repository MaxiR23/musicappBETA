from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, TypedDict

from services.db_protocol import DBClient
from services.library_view_cache import invalidate_library_view

LibraryKind = Literal["album", "playlist"]
LibrarySource = Literal["beatly", "external"]

class LibraryItem(TypedDict):
    id: str
    user_id: str
    kind: LibraryKind
    source: LibrarySource
    external_id: str
    title: str
    thumbnail_url: str
    artist: str
    artist_id: str
    album_id: str
    album_name: str
    added_at: str
    updated_at: str

class LibraryItemInput(TypedDict, total=False):
    kind: LibraryKind
    source: LibrarySource
    external_id: str
    title: str
    thumbnail_url: str
    artist: str
    artist_id: str
    album_id: str
    album_name: str

# ── DB READ ────────────────────────────────────────────────────
def _fetch_user_library(db: DBClient, user_id: str) -> List[LibraryItem]:
    """
    Carga todos los items del usuario desde DB.
    Sin cache propio: el cache unificado vive en library_view_service.
    """
    response = (
        db.table("library_items")
        .select("*")
        .eq("user_id", user_id)
        .order("added_at", desc=True)
        .execute()
    )
    rows: List[LibraryItem] = getattr(response, "data", None) or []
    return rows

# ── Pure helpers ───────────────────────────────────────────────
def _normalize_input(user_id: str, payload: LibraryItemInput) -> Dict[str, Any]:
    """Construye el row a insertar, aplicando defaults y el user_id."""
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "user_id": user_id,
        "kind": payload["kind"],
        "source": payload["source"],
        "external_id": payload["external_id"],
        "title": payload.get("title", ""),
        "thumbnail_url": payload.get("thumbnail_url", ""),
        "artist": payload.get("artist", ""),
        "artist_id": payload.get("artist_id", ""),
        "album_id": payload.get("album_id", ""),
        "album_name": payload.get("album_name", ""),
        "updated_at": now_iso,
    }

def _validate_input(payload: LibraryItemInput) -> Optional[str]:
    """Valida el payload. Devuelve mensaje de error o None si es válido."""
    if not payload.get("external_id"):
        return "external_id is required"
    if not payload.get("title"):
        return "title is required"
    kind = payload.get("kind")
    if kind not in ("album", "playlist"):
        return "kind must be 'album' or 'playlist'"
    source = payload.get("source")
    if source not in ("beatly", "external"):
        return "source must be 'beatly' or 'external'"
    return None

# ── QUERIES ────────────────────────────────────────────────────
def list_library_items(
    db: DBClient,
    user_id: str,
    kind: Optional[LibraryKind] = None,
) -> List[LibraryItem]:
    """Lista los items de la biblioteca, opcionalmente filtrados por kind."""
    all_items = _fetch_user_library(db, user_id)
    if kind is None:
        return all_items
    return [item for item in all_items if item.get("kind") == kind]

def get_library_item(
    db: DBClient,
    user_id: str,
    kind: LibraryKind,
    external_id: str,
) -> Optional[LibraryItem]:
    """Devuelve un item específico o None si no existe."""
    all_items = _fetch_user_library(db, user_id)
    for item in all_items:
        if item.get("kind") == kind and item.get("external_id") == external_id:
            return item
    return None

# ── MUTATIONS ──────────────────────────────────────────────────
def add_library_item(
    db: DBClient,
    user_id: str,
    payload: LibraryItemInput,
) -> Dict[str, Any]:
    """
    Agrega un item a la biblioteca del usuario.
    Si ya existe (mismo user_id + kind + external_id), actualiza el snapshot.
    """
    error = _validate_input(payload)
    if error:
        return {"error": "invalid_input", "detail": error}

    row = _normalize_input(user_id, payload)

    try:
        response = (
            db.table("library_items")
            .upsert(row, on_conflict="user_id,kind,external_id")
            .execute()
        )
        data = getattr(response, "data", None) or []
        if not data:
            return {"error": "add_failed", "detail": "no rows returned"}

        invalidate_library_view(user_id)
        return {"item": data[0]}
    except Exception as e:
        return {"error": "add_failed", "detail": str(e)[:200]}

def remove_library_item(
    db: DBClient,
    user_id: str,
    kind: LibraryKind,
    external_id: str,
) -> Dict[str, Any]:
    """Elimina un item de la biblioteca del usuario."""
    try:
        response = (
            db.table("library_items")
            .delete()
            .eq("user_id", user_id)
            .eq("kind", kind)
            .eq("external_id", external_id)
            .execute()
        )
        data = getattr(response, "data", None) or []
        if not data:
            return {"error": "not_found", "detail": "item not in library"}

        invalidate_library_view(user_id)
        return {"removed": data[0]}
    except Exception as e:
        return {"error": "remove_failed", "detail": str(e)[:200]}