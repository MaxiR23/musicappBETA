# INFO: Public share endpoints mapping internal payloads to the Next.js DTO contract.
from fastapi import APIRouter, HTTPException

from services.supabase_service import supabase_service
from services.album_service import get_album
from services.artist_service import get_artist
from services.playlist_service import get_public_playlist
from services.track_service import get_public_track
from services.genre_repo import get_playlist_by_id, get_playlist_thumbnails

router = APIRouter()

def _largest_thumb(thumbs: list | None) -> str:
    if not thumbs:
        return ""
    last = thumbs[-1]
    url = last.get("url") if isinstance(last, dict) else None
    return url if isinstance(url, str) else ""

def _to_album_public(album_id: str, payload: dict) -> dict:
    info = payload.get("info") or {}

    artists = info.get("included_artists") or []
    if not artists and info.get("artist_id"):
        artists = [{"id": info["artist_id"], "name": info.get("artist_name")}]

    thumbnail_url = _largest_thumb(info.get("thumbnails")) or _largest_thumb(info.get("strapline_thumbnail"))

    track_count = info.get("song_count")
    if not isinstance(track_count, int):
        track_count = len(payload.get("tracks") or [])

    return {
        "id": album_id,
        "title": info.get("title"),
        "artists": artists,
        "thumbnail_url": thumbnail_url,
        "year": info.get("year"),
        "track_count": track_count,
    }

def _to_artist_public(artist_id: str, payload: dict) -> dict:
    header = payload.get("header") or {}
    return {
        "id": artist_id,
        "name": header.get("name"),
        "thumbnail_url": _largest_thumb(header.get("thumbnails")),
        "description": header.get("description") or None,
    }

def _to_genre_playlist_public(playlist_id: str, row: dict, thumbnails: list[str]) -> dict:
    return {
        "id": playlist_id,
        "title": row.get("title"),
        "thumbnail_url": thumbnails[0] if thumbnails else "",
        "thumbnails": thumbnails,
        "track_count": row.get("track_count"),
    }

def _to_track_public(blob: dict) -> dict:
    duration_ms = blob.get("duration_seconds")
    duration_ms = duration_ms * 1000 if isinstance(duration_ms, int) else None

    album_id = blob.get("album_id")
    album = {"id": album_id, "title": blob.get("album_name")} if album_id else None

    return {
        "id": blob.get("id"),
        "title": blob.get("title"),
        "artists": blob.get("artists") or [],
        "thumbnail_url": blob.get("thumbnail") or "",
        "duration_ms": duration_ms,
        "album": album,
    }

@router.get("/album/{album_id}")
def public_album(album_id: str):
    payload = get_album(album_id)
    if not payload or payload.get("error") or not (payload.get("info") or {}).get("title"):
        raise HTTPException(status_code=404, detail="album_not_found")
    return _to_album_public(album_id, payload)

@router.get("/artist/{artist_id}")
def public_artist(artist_id: str):
    payload = get_artist(supabase_service, artist_id)
    if not payload or payload.get("error") or not (payload.get("header") or {}).get("name"):
        raise HTTPException(status_code=404, detail="artist_not_found")
    return _to_artist_public(artist_id, payload)

@router.get("/playlist/{playlist_id}")
def public_playlist(playlist_id: str):
    data = get_public_playlist(supabase_service, playlist_id)
    if data is None:
        raise HTTPException(status_code=404, detail="playlist_not_found")
    return data

@router.get("/genre-playlist/{playlist_id}")
def public_genre_playlist(playlist_id: str):
    row = get_playlist_by_id(supabase_service, playlist_id)
    if row is None:
        raise HTTPException(status_code=404, detail="genre_playlist_not_found")
    thumbnails = get_playlist_thumbnails(supabase_service, playlist_id)
    return _to_genre_playlist_public(playlist_id, row, thumbnails)

@router.get("/track/{track_id}")
def public_track(track_id: str):
    blob = get_public_track(track_id)
    if blob is None:
        raise HTTPException(status_code=404, detail="track_not_found")
    return _to_track_public(blob)