"""Endpoints de artistas."""
from fastapi import APIRouter, Query, Path
from services.artist_service import get_artist, get_all_albums, get_all_singles
from services.events_service import get_events_cached_only
from services.upcoming_releases_repo import get_upcoming_by_artist_id_cached
from services.audio_service import schedule_warm, get_warm_burst

router = APIRouter()

@router.get("/artist")
def get_artist_q(id: str = Query(...)):
    payload = get_artist(id)
    # Enriquecer upcomingEvents si está vacío (post-cache)
    if not payload.get("upcomingEvents"):
        artist_name = payload.get("header", {}).get("name")
        if artist_name:
            payload["upcomingEvents"] = get_events_cached_only(artist_name, limit=10)
    # Upcoming album
    try:
        payload["upcoming_album"] = get_upcoming_by_artist_id_cached(id)
    except Exception:
        payload["upcoming_album"] = None
    # Warming de top songs
    top_songs = payload.get("topSongs") or []
    ids = [t.get("id") for t in top_songs if isinstance(t, dict) and t.get("id")]
    schedule_warm(ids[:get_warm_burst()])
    return payload

@router.get("/artist/{id}")
def get_artist_p(id: str = Path(...)):
    payload = get_artist(id)
    # Enriquecer upcomingEvents si está vacío (post-cache)
    if not payload.get("upcomingEvents"):
        artist_name = payload.get("header", {}).get("name")
        if artist_name:
            payload["upcomingEvents"] = get_events_cached_only(artist_name, limit=10)
    # Upcoming album
    try:
        payload["upcoming_album"] = get_upcoming_by_artist_id_cached(id)
    except Exception:
        payload["upcoming_album"] = None
    # Warming de top songs
    top_songs = payload.get("topSongs") or []
    ids = [t.get("id") for t in top_songs if isinstance(t, dict) and t.get("id")]
    schedule_warm(ids[:get_warm_burst()])
    return payload

@router.get("/artist/{id}/albums")
def get_artist_all_albums(id: str = Path(...)):
    return get_all_albums(id)

@router.get("/artist/{id}/singles")
def get_artist_all_singles(id: str = Path(...)):
    return get_all_singles(id)