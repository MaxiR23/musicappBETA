"""
Library view service: orquestador de la grilla unificada de la biblioteca.

Combina 3 fuentes en un solo payload:
  - Playlists propias del user (playlist_service)
  - Liked Songs (likes_service) - siempre primero
  - Items saved: albums + playlists de terceros (library_service)

NO toca la DB directamente: delega en los services existentes, que tienen
sus propios caches de detalle. Solo cachea el resultado unificado (metadata
liviana para grilla, sin tracks adentro).
"""
from __future__ import annotations
from typing import List, Literal, Optional, TypedDict

from services.db_protocol import DBClient
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType
from services.library_view_cache import invalidate_library_view
from services.playlist_service import get_playlists
from services.likes_service import get_liked_playlist
from services.library_service import list_library_items

LibraryViewKind = Literal["liked", "own_playlist", "saved_playlist", "saved_album"]
SortMode = Literal["recents"]

class LibraryViewItem(TypedDict):
    kind: LibraryViewKind
    id: str
    title: str
    thumbnail_url: str
    subtitle: str
    sorted_at: str

# ── NORMALIZADORES ─────────────────────────────────────────────────────────────
def _normalize_own_playlist(pl: dict) -> LibraryViewItem:
    ptracks = pl.get("playlist_tracks") or []
    first_thumb = ""
    if ptracks:
        tracks = ptracks[0].get("tracks") or {}
        first_thumb = tracks.get("thumbnail_url") or ""
    return {
        "kind": "own_playlist",
        "id": pl["id"],
        "title": pl.get("title") or "",
        "thumbnail_url": first_thumb,
        "subtitle": "",
        "sorted_at": pl.get("created_at") or "",
    }

def _normalize_liked(liked: dict) -> LibraryViewItem:
    tracks = liked.get("tracks") or []
    first_thumb = tracks[0].get("thumbnail_url") if tracks else ""
    return {
        "kind": "liked",
        "id": "liked",
        "title": liked.get("title") or "Liked Songs",
        "thumbnail_url": first_thumb or "",
        "subtitle": f"{len(tracks)} tracks",
        "sorted_at": "",
    }

def _normalize_library_item(item: dict) -> LibraryViewItem:
    kind = "saved_album" if item.get("kind") == "album" else "saved_playlist"
    return {
        "kind": kind,
        "id": item.get("external_id") or "",
        "title": item.get("title") or "",
        "thumbnail_url": item.get("thumbnail_url") or "",
        "subtitle": item.get("artist") or "",
        "sorted_at": item.get("added_at") or "",
    }

# ── ORDEN ──────────────────────────────────────────────────────────────────────
def _apply_sort(items: List[LibraryViewItem], sort: SortMode) -> List[LibraryViewItem]:
    """
    Estructura: liked siempre primero, resto segun sort.
    Preparado para aceptar nuevos modos ('alphabetical', 'kind', etc.) sin romper firma.
    """
    liked = [i for i in items if i["kind"] == "liked"]
    rest = [i for i in items if i["kind"] != "liked"]

    if sort == "recents":
        rest.sort(key=lambda i: i.get("sorted_at") or "", reverse=True)
    else:
        rest.sort(key=lambda i: i.get("sorted_at") or "", reverse=True)

    return liked + rest

# ── QUERY ──────────────────────────────────────────────────────────────────────
def get_library_view(
    db: DBClient,
    user_id: str,
    sort: SortMode = "recents",
) -> dict:
    """
    Devuelve la grilla unificada de la biblioteca del user.
    Shape: {"items": [...], "sort": "recents"}
    """
    cache_suffix = f"{user_id}:{sort}"
    cached = get_cached(CacheType.LIBRARY_VIEW, suffix=cache_suffix)
    if cached is not None:
        return cached

    own = get_playlists(db, user_id) or []
    liked = get_liked_playlist(db, user_id) or {}
    saved = list_library_items(db, user_id) or []

    items: List[LibraryViewItem] = []
    items.append(_normalize_liked(liked))
    items.extend(_normalize_own_playlist(pl) for pl in own)
    items.extend(_normalize_library_item(it) for it in saved)

    items = _apply_sort(items, sort)

    payload = {"items": items, "sort": sort}
    set_cached(CacheType.LIBRARY_VIEW, payload, suffix=cache_suffix)
    return payload