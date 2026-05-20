"""
Repositorio para gestionar géneros, playlists curadas y sus tracks.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from services.db_protocol import DBClient

def build_genre_data(name: str, slug: str, sort_order: int, description: Optional[str] = None) -> Dict[str, Any]:
    return {
        "name": name,
        "slug": slug,
        "sort_order": sort_order,
        "description": description,
    }

def build_playlist_data(
    genre_id: str,
    title: str,
    category: Optional[str] = None,
    sort_order: int = 0,
    description: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "genre_id": genre_id,
        "title": title,
        "category": category,
        "sort_order": sort_order,
        "description": description,
        "thumbnail_url": thumbnail_url,
        "track_count": 0,
    }

def build_track_data(track: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "track_id": track.get("id") or track.get("track_id"),
        "title": track.get("title"),
        "artists": track.get("artists") or [],
        "album": track.get("album"),
        "album_id": track.get("album_id"),
        "duration_seconds": track.get("duration_seconds"),
        "thumbnail_url": track.get("thumbnail_url") or track.get("thumb"),
    }

def build_playlist_track_item(position: int, track_id: str, track_data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "position": position,
        "track_id": track_id,
        "title": track_data.get("title"),
        "artists": track_data.get("artists") or [],
        "album": track_data.get("album"),
        "album_id": track_data.get("album_id"),
        "duration_seconds": track_data.get("duration_seconds"),
        "thumbnail_url": track_data.get("thumbnail_url"),
    }

def extract_unique_categories(rows: List[Dict[str, Any]]) -> List[str]:
    return sorted(list(set(
        row["category"]
        for row in rows
        if row.get("category")
    )))

def build_thumbnails_map(rows: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    thumbnails_map: Dict[str, List[str]] = {}
    for row in rows:
        pid = row.get("playlist_id")
        if pid not in thumbnails_map:
            thumbnails_map[pid] = []
        if row.get("thumbnail_url"):
            thumbnails_map[pid].append(row.get("thumbnail_url"))
    return thumbnails_map

# ── IO (escritura) ───────────────────────────────────────
def upsert_genre(db: DBClient, name: str, slug: str, sort_order: int, description: Optional[str] = None) -> str:
    """Inserta o actualiza un género. Devuelve el ID del género."""
    data = build_genre_data(name, slug, sort_order, description)
    result = db.table("genres").upsert(data, on_conflict="slug").execute()
    if not result.data:
        raise RuntimeError(f"Error insertando género {name}")
    return result.data[0]["id"]

def upsert_genre_playlist(
    db: DBClient,
    genre_id: str,
    title: str,
    category: Optional[str] = None,
    sort_order: int = 0,
    description: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
) -> str:
    """Inserta o actualiza una playlist curada. Devuelve el ID de la playlist."""
    data = build_playlist_data(genre_id, title, category, sort_order, description, thumbnail_url)
    existing = db.table("genre_playlists").select("id").eq("genre_id", genre_id).eq("title", title).execute()

    if existing.data:
        playlist_id = existing.data[0]["id"]
        db.table("genre_playlists").update(data).eq("id", playlist_id).execute()
        return playlist_id
    else:
        result = db.table("genre_playlists").insert(data).execute()
        if not result.data:
            raise RuntimeError(f"Error insertando playlist {title}")
        return result.data[0]["id"]

def upsert_track(db: DBClient, track: Dict[str, Any]) -> None:
    """Inserta o actualiza un track en la tabla tracks."""
    data = build_track_data(track)
    db.table("tracks").upsert(data, on_conflict="track_id").execute()

def insert_genre_playlist_tracks(db: DBClient, playlist_id: str, tracks: List[Dict[str, Any]]) -> int:
    """
    Sincroniza los tracks de una playlist curada por DIFF.

    No borra y reinserta todo: compara el estado actual en DB contra el
    deseado y solo toca lo que cambio (membresia Y posicion). Si nada
    cambio, NO escribe nada y updated_at queda igual.

    Devuelve la cantidad de filas escritas (insertadas + movidas).
    """
    # 1. Estado deseado: orden de la fuente, dedup por track_id (gana la
    #    primera aparicion), descarta sin id, posiciones compactas 1..N.
    desired_order: List[str] = []
    seen: set[str] = set()
    track_by_id: Dict[str, Dict[str, Any]] = {}
    for track in tracks:
        tid = track.get("id") or track.get("track_id")
        if not tid or tid in seen:
            continue
        seen.add(tid)
        desired_order.append(tid)
        track_by_id[tid] = track

    # 2. Asegurar que cada track exista en public.tracks (FK + metadata).
    #    Si el upsert falla, lo sacamos del deseado para no romper la FK.
    valid_order: List[str] = []
    for tid in desired_order:
        try:
            upsert_track(db, track_by_id[tid])
            valid_order.append(tid)
        except Exception as e:
            print(f"  Error upserting track {tid}: {e}")

    desired: Dict[str, int] = {tid: i for i, tid in enumerate(valid_order, start=1)}

    # 3. Estado actual en DB.
    existing_resp = (
        db.table("genre_playlist_tracks")
        .select("track_id, position")
        .eq("playlist_id", playlist_id)
        .execute()
    )
    existing: Dict[str, int] = {
        row["track_id"]: row["position"]
        for row in (existing_resp.data or [])
        if row.get("track_id") is not None
    }

    # 4. Diff.
    to_delete = [tid for tid in existing if tid not in desired]
    to_insert = [tid for tid in desired if tid not in existing]
    to_move = [
        tid for tid in desired
        if tid in existing and existing[tid] != desired[tid]
    ]

    if not (to_delete or to_insert or to_move):
        print(f"  Sin cambios, no se toca nada (updated_at intacto)")
        return 0

    # 5. Borrar TODO lo que cambia de lugar o sobra ANTES de insertar.
    #    Libera track_ids y posiciones -> el insert no choca el UNIQUE,
    #    sea (playlist_id, track_id) o (playlist_id, position).
    remove_ids = to_delete + to_move
    if remove_ids:
        (
            db.table("genre_playlist_tracks")
            .delete()
            .eq("playlist_id", playlist_id)
            .in_("track_id", remove_ids)
            .execute()
        )

    # 6. Insertar lo nuevo + lo que se movio, en orden de posicion final.
    insert_ids = to_insert + to_move
    payload = [
        {
            "playlist_id": playlist_id,
            "track_id": tid,
            "position": desired[tid],
        }
        for tid in sorted(insert_ids, key=lambda t: desired[t])
    ]
    if payload:
        db.table("genre_playlist_tracks").insert(payload).execute()

    # 7. Hubo cambios: bumpear updated_at del padre con un UPDATE explicito.
    #    Seteamos el valor a mano para no depender de que el trigger exista.
    db.table("genre_playlists").update(
        {"updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", playlist_id).execute()

    print(f"  Diff: +{len(to_insert)} insertados, -{len(to_delete)} borrados, ~{len(to_move)} movidos")
    return len(to_insert) + len(to_move)

def clear_genre_playlists(db: DBClient, genre_id: str) -> None:
    """Elimina todas las playlists de un género."""
    db.table("genre_playlists").delete().eq("genre_id", genre_id).execute()

# ── IO (lectura) ─────────────────────────────────────────
def get_all_genres(db: DBClient) -> List[Dict[str, Any]]:
    """Obtiene todos los géneros ordenados por sort_order."""
    result = db.table("genres") \
        .select("id, name, slug, sort_order, created_at") \
        .order("sort_order") \
        .execute()
    return result.data or []

def get_genre_by_slug(db: DBClient, slug: str) -> Optional[Dict[str, Any]]:
    """Obtiene un género por su slug."""
    result = db.table("genres") \
        .select("id, name, slug, sort_order, created_at") \
        .eq("slug", slug) \
        .execute()
    return result.data[0] if result.data else None

def get_playlists_by_genre(db: DBClient, genre_id: str, category: Optional[str] = None) -> List[Dict[str, Any]]:
    """Obtiene las playlists de un género con thumbnails."""
    query = db.table("genre_playlists") \
        .select("id, title, category, track_count, sort_order, created_at") \
        .eq("genre_id", genre_id)

    if category:
        query = query.eq("category", category)

    result = query.order("sort_order").execute()
    playlists = result.data or []

    if not playlists:
        return []

    playlist_ids = [p["id"] for p in playlists]

    try:
        thumbnails_result = db.rpc(
            'get_playlist_thumbnails',
            {'playlist_ids': playlist_ids, 'limit_per_playlist': 4}
        ).execute()
        thumbnails_map = build_thumbnails_map(thumbnails_result.data or [])
    except Exception as e:
        print(f"Error obteniendo thumbnails: {e}")
        thumbnails_map = {}

    for playlist in playlists:
        playlist["thumbnails"] = thumbnails_map.get(playlist["id"], [])

    return playlists

def get_playlist_by_id(db: DBClient, playlist_id: str) -> Optional[Dict[str, Any]]:
    """Obtiene una playlist por su ID."""
    result = db.table("genre_playlists") \
        .select("id, title, track_count, category, created_at, updated_at") \
        .eq("id", playlist_id) \
        .execute()
    return result.data[0] if result.data else None

def get_playlist_tracks(db: DBClient, playlist_id: str, limit: Optional[int] = 100) -> List[Dict[str, Any]]:
    """Obtiene los tracks de una playlist ordenados por posición."""
    query = db.table("genre_playlist_tracks") \
        .select("position, track_id") \
        .eq("playlist_id", playlist_id) \
        .order("position")

    if limit:
        query = query.limit(limit)

    result = query.execute()
    if not result.data:
        return []

    track_ids = [row["track_id"] for row in result.data if row.get("track_id")]
    if not track_ids:
        return []

    tracks_result = db.table("tracks") \
        .select("track_id, title, artists, album, album_id, duration_seconds, thumbnail_url") \
        .in_("track_id", track_ids) \
        .execute()

    tracks_dict = {t["track_id"]: t for t in (tracks_result.data or [])}

    return [
        build_playlist_track_item(row.get("position"), row.get("track_id"), tracks_dict.get(row.get("track_id"), {}))
        for row in result.data
    ]

def get_genre_categories(db: DBClient, genre_id: str) -> List[str]:
    """Obtiene las categorías únicas de un género."""
    result = db.table("genre_playlists") \
        .select("category") \
        .eq("genre_id", genre_id) \
        .not_.is_("category", "null") \
        .execute()
    return extract_unique_categories(result.data or [])