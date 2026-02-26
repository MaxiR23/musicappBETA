# routes/search.py
"""Endpoint de búsqueda."""
from fastapi import APIRouter, Query
from services.search_service import search, get_warm_ids
from services.audio_service import schedule_warm

router = APIRouter()

@router.get("/search")
def search_music(q: str = Query(..., description="Texto a buscar")):
    result = search(q)
    # Warming
    ids = get_warm_ids(result)
    schedule_warm(ids)
    return result