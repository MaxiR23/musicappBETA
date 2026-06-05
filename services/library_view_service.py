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
def _normalize_own_playlist(pl: dict, owner_name: str) -> LibraryViewItem:
    return {
        "kind": "own_playlist",
        "id": pl["id"],
        "title": pl.get("title") or "",
        "thumbnail_url": "",
        "subtitle": f"Playlist • {owner_name}",
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

def _normalize_library_item(item: dict, owner_names: dict[str, str]) -> LibraryViewItem:
    kind = "saved_album" if item.get("kind") == "album" else "saved_playlist"
    source = item.get("source") or "external"
    external_id = item.get("external_id") or ""

    if kind == "saved_album":
        artist = item.get("artist") or ""
        subtitle = f"Album • {artist}" if artist else "Album"
    elif source == "external":
        owner = owner_names.get(external_id)
        subtitle = f"Playlist • {owner}" if owner else "Playlist"
    else:
        # Playlists internas de Beatly (genre/replay/presenting).
        subtitle = "Playlist • Beatly"

    return {
        "kind": kind,
        "source": source,
        "id": item.get("external_id") or "",
        "title": item.get("title") or "",
        "thumbnail_url": item.get("thumbnail_url") or "",
        "subtitle": subtitle,
        "sorted_at": item.get("added_at") or "",
    }

# ── PROFILE / OWNER NAME ───────────────────────────────────────────────────────
def _fetch_profile(db: DBClient, user_id: str) -> dict:
    """Trae username y display_name del user actual, una sola llamada."""
    try:
        resp = (
            db.table("profiles")
            .select("username, display_name")
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )
        return getattr(resp, "data", None) or {}
    except Exception as e:
        print(f"[library_view] profile fetch failed: {e}")
        return {}

def _owner_name(profile: dict) -> str:
    """Fallback: username -> display_name -> 'Usuario'."""
    return profile.get("username") or profile.get("display_name") or "User"

# ── THUMBNAILS (MOSAICOS) ──────────────────────────────────────────────────────
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

def _fetch_genre_playlist_thumbnails(
    db: DBClient,
    playlist_ids: List[str],
) -> dict[str, List[str]]:
    """
    Trae hasta 4 thumbnails por cada genre playlist saved en library.
    Usa get_playlist_thumbnails (RPC generica, equivalente para genre).
    Retorna: { playlist_id: [url, url, ...] }
    """
    if not playlist_ids:
        return {}

    try:
        resp = db.rpc(
            "get_playlist_thumbnails",
            {"playlist_ids": playlist_ids, "limit_per_playlist": 4},
        ).execute()
        rows = resp.data or []
    except Exception as e:
        print(f"[library_view] get_playlist_thumbnails failed: {e}")
        return {}

    result: dict[str, List[str]] = {}
    for row in rows:
        pid = row.get("playlist_id")
        url = row.get("thumbnail_url")
        if not pid or not url:
            continue
        result.setdefault(pid, []).append(url)
    return result

def _fetch_replay_thumbnails(db: DBClient, user_id: str) -> List[str]:
    """
    Trae hasta 4 thumbnails de las songs del replay del user.
    Usa get_replay_songs con p_limit=4.
    """
    try:
        resp = db.rpc(
            "get_replay_songs",
            {"p_user_id": user_id, "p_limit": 4},
        ).execute()
        rows = resp.data or []
    except Exception as e:
        print(f"[library_view] get_replay_songs failed: {e}")
        return []

    return [row.get("thumbnail_url") for row in rows if row.get("thumbnail_url")]

def _fetch_external_owner_names(
    db: DBClient,
    playlist_ids: List[str],
) -> dict[str, str]:
    """
    Resuelve { playlist_id: owner_name } para playlists externas, en lotes.
    Dos pasos: playlists -> owner_id, luego profiles -> nombre.
    Fallback username -> display_name. Robusto: si algo falla, devuelve lo que pudo.
    """
    if not playlist_ids:
        return {}

    CHUNK = 100
    # Paso 1: playlist_id -> owner_id
    pid_to_owner: dict[str, str] = {}
    for start in range(0, len(playlist_ids), CHUNK):
        batch = playlist_ids[start:start + CHUNK]
        try:
            resp = db.table("playlists").select("id, owner_id").in_("id", batch).execute()
            for row in (resp.data or []):
                if row.get("id") and row.get("owner_id"):
                    pid_to_owner[row["id"]] = row["owner_id"]
        except Exception as e:
            print(f"[library_view] owner ids batch failed: {e}")
            continue

    if not pid_to_owner:
        return {}

    # Paso 2: owner_id -> nombre (profiles)
    owner_ids = list(set(pid_to_owner.values()))
    owner_to_name: dict[str, str] = {}
    for start in range(0, len(owner_ids), CHUNK):
        batch = owner_ids[start:start + CHUNK]
        try:
            resp = db.table("profiles").select("id, username, display_name").in_("id", batch).execute()
            for row in (resp.data or []):
                name = row.get("username") or row.get("display_name")
                if row.get("id") and name:
                    owner_to_name[row["id"]] = name
        except Exception as e:
            print(f"[library_view] profile names batch failed: {e}")
            continue

    # Combinar: playlist_id -> nombre
    result: dict[str, str] = {}
    for pid, owner_id in pid_to_owner.items():
        name = owner_to_name.get(owner_id)
        if name:
            result[pid] = name
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
    profile = _fetch_profile(db, user_id)
    owner_name = _owner_name(profile)

    items: List[LibraryViewItem] = []
    items.append(_normalize_liked(liked))
    items.extend(_normalize_own_playlist(pl, owner_name) for pl in own)
    external_ids = [
        it.get("external_id") for it in saved
        if it.get("kind") == "playlist"
        and it.get("source") == "external"
        and it.get("external_id")
    ]
    owner_names = _fetch_external_owner_names(db, external_ids)
    items.extend(_normalize_library_item(it, owner_names) for it in saved)

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

    # Enriquecer genre playlists saved con mosaico (hasta 4 thumbs).
    genre_ids = [
        it["id"] for it in items
        if it.get("kind") == "saved_playlist" and it.get("source") == "genre"
    ]
    if genre_ids:
        genre_thumbs = _fetch_genre_playlist_thumbnails(db, genre_ids)
        if genre_thumbs:
            for it in items:
                if it.get("kind") != "saved_playlist" or it.get("source") != "genre":
                    continue
                urls = genre_thumbs.get(it["id"]) or []
                if urls:
                    it["thumbnail_urls"] = urls
                    it["thumbnail_url"] = urls[0]

    # Enriquecer replay con mosaico (solo si esta saved en library).
    has_replay = any(
        it.get("kind") == "saved_playlist" and it.get("source") == "replay"
        for it in items
    )
    if has_replay:
        replay_thumbs = _fetch_replay_thumbnails(db, user_id)
        if replay_thumbs:
            for it in items:
                if it.get("kind") == "saved_playlist" and it.get("source") == "replay":
                    it["thumbnail_urls"] = replay_thumbs
                    it["thumbnail_url"] = replay_thumbs[0]

    # Enriquecer playlists externas (ajenas) con mosaico (hasta 4 thumbs).
    external_pl_ids = [
        it["id"] for it in items
        if it.get("kind") == "saved_playlist" and it.get("source") == "external"
    ]
    if external_pl_ids:
        external_thumbs = _fetch_own_playlist_thumbnails(db, external_pl_ids)
        if external_thumbs:
            for it in items:
                if it.get("kind") != "saved_playlist" or it.get("source") != "external":
                    continue
                urls = external_thumbs.get(it["id"]) or []
                if urls:
                    it["thumbnail_urls"] = urls
                    it["thumbnail_url"] = urls[0]

    items = _apply_sort(items, sort)

    payload = {"items": items, "sort": sort}
    set_cached(CacheType.LIBRARY_VIEW, payload, suffix=cache_suffix)
    return payload