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

class LibraryViewItem(TypedDict, total=False):
    kind: LibraryViewKind
    source: str
    id: str
    title: str
    thumbnail_url: str
    subtitle: str
    sorted_at: str
    thumbnail_urls: list[str]

# ── NORMALIZADORES ─────────────────────────────────────────────────────────────
def _normalize_own_playlist(pl: dict) -> LibraryViewItem:
    return {
        "kind": "own_playlist",
        "id": pl["id"],
        "title": pl.get("title") or "",
        "thumbnail_url": "",
        "subtitle": "",
        "sorted_at": pl.get("created_at") or "",
        "thumbnail_urls": [],
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
        "source": item.get("source") or "external",
        "id": item.get("external_id") or "",
        "title": item.get("title") or "",
        "thumbnail_url": item.get("thumbnail_url") or "",
        "subtitle": item.get("artist") or "",
        "sorted_at": item.get("added_at") or "",
    }

def _fetch_own_playlist_thumbnails(
    db: DBClient,
    playlist_ids: List[str],
) -> dict[str, List[str]]:
    """
    Trae hasta 4 thumbnails por cada playlist propia, en UNA sola llamada.
    Usa get_user_playlist_thumbnails (funcion SQL en Supabase).
    Retorna: { playlist_id: [url, url, ...] }
    """
    if not playlist_ids:
        return {}

    try:
        resp = db.rpc(
            "get_user_playlist_thumbnails",
            {"playlist_ids": playlist_ids, "limit_per_playlist": 4},
        ).execute()
        rows = resp.data or []
    except Exception as e:
        print(f"[library_view] get_user_playlist_thumbnails failed: {e}")
        return {}

    result: dict[str, List[str]] = {}
    for row in rows:
        pid = row.get("playlist_id")
        url = row.get("thumbnail_url")
        if not pid or not url:
            continue
        result.setdefault(pid, []).append(url)
    return result

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

    # Enriquecer playlists propias con mosaico (hasta 4 thumbs).
    own_ids = [pl["id"] for pl in own if pl.get("id")]
    thumbs_by_pid = _fetch_own_playlist_thumbnails(db, own_ids)
    if thumbs_by_pid:
        for it in items:
            if it.get("kind") != "own_playlist":
                continue
            urls = thumbs_by_pid.get(it["id"]) or []
            if urls:
                it["thumbnail_urls"] = urls
                it["thumbnail_url"] = urls[0]

    items = _apply_sort(items, sort)

    payload = {"items": items, "sort": sort}
    set_cached(CacheType.LIBRARY_VIEW, payload, suffix=cache_suffix)
    return payload