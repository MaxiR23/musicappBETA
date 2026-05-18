"""Endpoints de artistas."""
from fastapi import APIRouter, Query, Path, Depends
from fastapi.responses import JSONResponse

from core.dependencies import get_db
from services.db_protocol import DBClient
from services.artist_service import get_artist, get_all_albums, get_all_singles
from services.presenting_service import get_presenting
from services.events_service import get_events_cached_only
from services.upcoming_releases_repo import get_upcoming_by_artist_id_cached
from services.audio_service import schedule_warm, get_warm_burst

router = APIRouter()

# ── HELPERS ──────────────────────────────────────────────
def _enrich_artist_payload(db: DBClient, payload: dict, artist_id: str) -> dict:
    """Enriquece payload con eventos y upcoming album."""
    if not payload.get("upcoming_events"):
        artist_name = payload.get("header", {}).get("name")
        if artist_name:
            payload["upcoming_events"] = get_events_cached_only(artist_name, limit=10)
    try:
        payload["upcoming_album"] = get_upcoming_by_artist_id_cached(db, artist_id)
    except Exception:
        payload["upcoming_album"] = None
    return payload

def _schedule_warm_for_top_songs(payload: dict) -> None:
    """Agenda warm de top songs."""
    top_songs = payload.get("top_songs") or []
    ids = [t.get("id") for t in top_songs if isinstance(t, dict) and t.get("id")]
    schedule_warm(ids[:get_warm_burst()])

def _handle_artist_request(db: DBClient, artist_id: str):
    """Lógica común para obtener artista."""
    try:
        payload = get_artist(db, artist_id)
        if isinstance(payload, dict) and payload.get("error"):
            return JSONResponse(status_code=502, content=payload)
        payload = _enrich_artist_payload(db, payload, artist_id)
        _schedule_warm_for_top_songs(payload)
        return payload
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": "service_unavailable", "detail": str(e)})

# ── ENDPOINTS ────────────────────────────────────────────
@router.get("/artist")
def get_artist_q(id: str = Query(...), db: DBClient = Depends(get_db)):
    return _handle_artist_request(db, id)

@router.get("/artist/{id}")
def get_artist_p(id: str = Path(...), db: DBClient = Depends(get_db)):
    return _handle_artist_request(db, id)

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
    
@router.get("/artist/{id}/presenting")
def get_artist_presenting(id: str = Path(...), db: DBClient = Depends(get_db)):
    try:
        payload = get_presenting(db, id)
        if isinstance(payload, dict) and payload.get("error"):
            status = 404 if payload.get("error") == "no_presenting" else 502
            return JSONResponse(status_code=status, content=payload)
        return payload
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": "service_unavailable", "detail": str(e)})