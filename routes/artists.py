"""Endpoints de artistas."""
from fastapi import APIRouter, Query, Path
from fastapi.responses import JSONResponse
from services.artist_service import get_artist, get_all_albums, get_all_singles
from services.events_service import get_events_cached_only
from services.upcoming_releases_repo import get_upcoming_by_artist_id_cached
from services.audio_service import schedule_warm, get_warm_burst

router = APIRouter()

@router.get("/artist")
def get_artist_q(id: str = Query(...)):
    try:
        payload = get_artist(id)
        if isinstance(payload, dict) and payload.get("error"):
            return JSONResponse(status_code=502, content=payload)
        if not payload.get("upcoming_events"):
            artist_name = payload.get("header", {}).get("name")
            if artist_name:
                payload["upcoming_events"] = get_events_cached_only(artist_name, limit=10)
        try:
            payload["upcoming_album"] = get_upcoming_by_artist_id_cached(id)
        except Exception:
            payload["upcoming_album"] = None
        top_songs = payload.get("top_songs") or []
        ids = [t.get("id") for t in top_songs if isinstance(t, dict) and t.get("id")]
        schedule_warm(ids[:get_warm_burst()])
        return payload
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": "service_unavailable", "detail": str(e)})

@router.get("/artist/{id}")
def get_artist_p(id: str = Path(...)):
    try:
        payload = get_artist(id)
        if isinstance(payload, dict) and payload.get("error"):
            return JSONResponse(status_code=502, content=payload)
        if not payload.get("upcoming_events"):
            artist_name = payload.get("header", {}).get("name")
            if artist_name:
                payload["upcoming_events"] = get_events_cached_only(artist_name, limit=10)
        try:
            payload["upcoming_album"] = get_upcoming_by_artist_id_cached(id)
        except Exception:
            payload["upcoming_album"] = None
        top_songs = payload.get("top_songs") or []
        ids = [t.get("id") for t in top_songs if isinstance(t, dict) and t.get("id")]
        schedule_warm(ids[:get_warm_burst()])
        return payload
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": "service_unavailable", "detail": str(e)})

@router.get("/artist/{id}/albums")
def get_artist_all_albums(id: str = Path(...)):
    try:
        payload = get_all_albums(id)
        if isinstance(payload, dict) and payload.get("error"):
            return JSONResponse(status_code=502, content=payload)
        return payload
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": "service_unavailable", "detail": str(e)})

@router.get("/artist/{id}/singles")
def get_artist_all_singles(id: str = Path(...)):
    try:
        payload = get_all_singles(id)
        if isinstance(payload, dict) and payload.get("error"):
            return JSONResponse(status_code=502, content=payload)
        return payload
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": "service_unavailable", "detail": str(e)})