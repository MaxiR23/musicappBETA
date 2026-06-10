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
        res = get_user_stations(db, user_id)
        if not res.get("ok"):
            status = 502 if res.get("reason") == "error" else 200
            return JSONResponse(status_code=status, content=res)  # 200: data not found for existing resource
        return {"stations": res["stations"]}
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})

@router.get("/artist/{artist_id}")
async def get_artist_station_route(artist_id: str):
    try:
        res = get_station_tracks(artist_id)
        if not res.get("ok"):
            status = 502 if res.get("reason") == "error" else 200
            return JSONResponse(status_code=status, content=res)  # 200: data not found for existing resource
        return {"tracks": res["tracks"]}
    except Exception as e:
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})
