from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from services.station_service import (
    get_user_stations,
    get_station_tracks,
)
from services.db_protocol import DBClient
from core.dependencies import get_db, get_current_user_id

router = APIRouter(tags=["station"])

@router.get("/user")
async def get_user_stations_route(
    db: DBClient = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    try:
        stations = get_user_stations(db, user_id)
        if stations is None:
            return JSONResponse(status_code=404, content={"error": "no_stations_available"})
        return {"stations": stations}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "stations_error", "detail": str(e)})

@router.get("/artist/{artist_id}")
async def get_artist_station_route(artist_id: str):
    try:
        tracks = get_station_tracks(artist_id)
        if tracks is None:
            return JSONResponse(status_code=404, content={"error": "station_not_found"})
        return {"tracks": tracks}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "station_error", "detail": str(e)})