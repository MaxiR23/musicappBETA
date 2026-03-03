# services/genre_repo.py
"""
Repositorio para gestionar géneros, playlists curadas y sus tracks.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from services.supabase_service import supabase_service as sb

def upsert_genre(name: str, slug: str, sort_order: int, description: Optional[str] = None) -> str:
    """
    Inserta o actualiza un género. Devuelve el ID del género.
    
    Args:
        name: Nombre del género (ej: "Dance & Electronic")
        slug: Slug URL-friendly (ej: "dance-electronic")
        sort_order: Orden de visualización
        description: Descripción opcional
    
    Returns:
        UUID del género
    """
    data = {
        "name": name,
        "slug": slug,
        "sort_order": sort_order,
        "description": description,
    }
    
    # Upsert por slug (unique)
    result = sb.table("genres").upsert(data, on_conflict="slug").execute()
    
    if not result.data:
        raise RuntimeError(f"Error insertando género {name}")
    
    return result.data[0]["id"]


def upsert_genre_playlist(
    genre_id: str,
    title: str,
    category: Optional[str] = None,
    sort_order: int = 0,
    description: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
) -> str:
    """
    Inserta o actualiza una playlist curada. Devuelve el ID de la playlist.
    
    Args:
        genre_id: UUID del género
        title: Título de la playlist
        category: Subcategoría opcional (ej: "1970s")
        sort_order: Orden dentro del género
        description: Descripción opcional
        thumbnail_url: URL del thumbnail opcional
    
    Returns:
        UUID de la playlist
    """
    data = {
        "genre_id": genre_id,
        "title": title,
        "category": category,
        "sort_order": sort_order,
        "description": description,
        "thumbnail_url": thumbnail_url,
        "track_count": 0,  # Se actualiza automáticamente con trigger
    }
    
    # Buscar si ya existe
    existing = sb.table("genre_playlists").select("id").eq("genre_id", genre_id).eq("title", title).execute()
    
    if existing.data:
        # Update
        playlist_id = existing.data[0]["id"]
        sb.table("genre_playlists").update(data).eq("id", playlist_id).execute()
        return playlist_id
    else:
        # Insert
        result = sb.table("genre_playlists").insert(data).execute()
        if not result.data:
            raise RuntimeError(f"Error insertando playlist {title}")
        return result.data[0]["id"]


def upsert_track(track: Dict[str, Any]) -> None:
    """
    Inserta o actualiza un track en la tabla tracks.
    
    Args:
        track: Dict con formato {track_id, title, artist, album, duration_seconds, thumbnail_url, artist_id}
    """
    # TODO: map_track should return duration_seconds directly instead of duration_seconds for consistency
    data = {
        "track_id": track.get("id") or track.get("track_id"),
        "title": track.get("title"),
        "artist": track.get("artist"),
        "album": track.get("album"),
        "duration_seconds": track.get("duration_seconds") or (track.get("duration_seconds") * 1000 if track.get("duration_seconds") else None),
        "thumbnail_url": track.get("thumbnail_url") or track.get("thumb"),
        "artist_id": track.get("artist_id") or track.get("artist_id"),
    }
    
    # Upsert por track_id (unique constraint)
    sb.table("tracks").upsert(data, on_conflict="track_id").execute()

def insert_genre_playlist_tracks(playlist_id: str, tracks: List[Dict[str, Any]]) -> int:
    """
    Inserta tracks en una playlist curada. Reemplaza los tracks existentes.
    
    Args:
        playlist_id: UUID de la playlist
        tracks: Lista de tracks con metadata
    
    Returns:
        Número de tracks insertados
    """
    # 1. Borrar tracks existentes de esta playlist
    sb.table("genre_playlist_tracks").delete().eq("playlist_id", playlist_id).execute()
    
    # 2. Insertar tracks uno por uno (upsert en tabla tracks primero)
    inserted = 0
    for position, track in enumerate(tracks, start=1):
        try:
            # Upsert el track en tabla tracks
            upsert_track(track)
            
            # Insertar referencia en genre_playlist_tracks
            track_id = track.get("id") or track.get("track_id")
            
            if not track_id:
                continue
            
            sb.table("genre_playlist_tracks").insert({
                "playlist_id": playlist_id,
                "track_id": track_id,
                "position": position,
            }).execute()
            
            inserted += 1
            
        except Exception as e:
            print(f"Error insertando track {track.get('title')}: {e}")
            continue
    
    return inserted


def clear_genre_playlists(genre_id: str) -> None:
    """
    Elimina todas las playlists de un género (útil para re-popular).
    """
    sb.table("genre_playlists").delete().eq("genre_id", genre_id).execute()


# ============================================================================
# FUNCIONES DE LECTURA (para endpoints)
# ============================================================================

def get_all_genres() -> List[Dict[str, Any]]:
    """
    Obtiene todos los géneros ordenados por sort_order.
    """
    result = sb.table("genres") \
        .select("id, name, slug, sort_order, created_at") \
        .order("sort_order") \
        .execute()
    
    return result.data or []


def get_genre_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """
    Obtiene un género por su slug.
    """
    result = sb.table("genres") \
        .select("id, name, slug, sort_order, created_at") \
        .eq("slug", slug) \
        .execute()
    
    return result.data[0] if result.data else None

def get_playlists_by_genre(
    genre_id: str,
    category: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Obtiene las playlists de un género.
    Si category se especifica, filtra por esa categoría.
    Incluye los primeros 4 thumbnails de cada playlist.
    """
    query = sb.table("genre_playlists") \
        .select("id, title, category, track_count, sort_order, created_at") \
        .eq("genre_id", genre_id)
    
    if category:
        query = query.eq("category", category)
    
    result = query.order("sort_order").execute()
    
    playlists = result.data or []
    
    if not playlists:
        return []
    
    # Obtener los primeros 4 thumbnails de cada playlist con RPC
    playlist_ids = [p["id"] for p in playlists]
    
    try:
        thumbnails_result = sb.rpc(
            'get_playlist_thumbnails',
            {'playlist_ids': playlist_ids, 'limit_per_playlist': 4}
        ).execute()
        
        # Organizar thumbnails por playlist_id
        thumbnails_map = {}
        for row in (thumbnails_result.data or []):
            pid = row.get("playlist_id")
            if pid not in thumbnails_map:
                thumbnails_map[pid] = []
            thumbnails_map[pid].append(row.get("thumbnail_url"))
        
    except Exception as e:
        print(f"Error obteniendo thumbnails: {e}")
        thumbnails_map = {}
    
    # Agregar thumbnails a cada playlist
    for playlist in playlists:
        playlist["thumbnails"] = thumbnails_map.get(playlist["id"], [])
    
    return playlists

def get_playlist_by_id(playlist_id: str) -> Optional[Dict[str, Any]]:
    """
    Obtiene una playlist por su ID.
    """
    result = sb.table("genre_playlists") \
        .select("id, title, track_count, category, created_at") \
        .eq("id", playlist_id) \
        .execute()
    
    return result.data[0] if result.data else None


def get_playlist_tracks(
    playlist_id: str,
    limit: Optional[int] = 100
) -> List[Dict[str, Any]]:
    """
    Obtiene los tracks de una playlist ordenados por posición.
    """
    # Query 1: Obtener las referencias de tracks
    query = sb.table("genre_playlist_tracks") \
        .select("position, track_id") \
        .eq("playlist_id", playlist_id) \
        .order("position")
    
    if limit:
        query = query.limit(limit)
    
    result = query.execute()
    
    if not result.data:
        return []
    
    # Query 2: Obtener los datos completos de los tracks
    track_ids = [row["track_id"] for row in result.data if row.get("track_id")]
    
    if not track_ids:
        return []
    
    tracks_result = sb.table("tracks") \
        .select("track_id, title, artist, album, duration_seconds, thumbnail_url, artist_id") \
        .in_("track_id", track_ids) \
        .execute()
    
    # Crear un dict para lookup rápido
    tracks_dict = {t["track_id"]: t for t in (tracks_result.data or [])}
    
    # Combinar los resultados
    tracks = []
    for row in result.data:
        track_id = row.get("track_id")
        track_data = tracks_dict.get(track_id, {})
        
        tracks.append({
            "position": row.get("position"),
            "track_id": track_id,
            "title": track_data.get("title"),
            "artist": track_data.get("artist"),
            "album": track_data.get("album"),
            "duration_seconds": track_data.get("duration_seconds"),
            "thumbnail_url": track_data.get("thumbnail_url"),
            "artist_id": track_data.get("artist_id"),
        })
    
    return tracks

def get_genre_categories(genre_id: str) -> List[str]:
    """
    Obtiene las categorías únicas de un género.
    """
    result = sb.table("genre_playlists") \
        .select("category") \
        .eq("genre_id", genre_id) \
        .not_.is_("category", "null") \
        .execute()
    
    categories = sorted(list(set(
        row["category"] 
        for row in (result.data or [])
        if row.get("category")
    )))
    
    return categories