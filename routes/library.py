from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse

from core.dependencies import get_current_user_id, get_user_db
from services.db_protocol import DBClient
from services.library_service import (
    add_library_item,
    remove_library_item,
)

from services.library_view_service import get_library_view

router = APIRouter(tags=["library"])

@router.get("")
async def list_library_route(
    sort: str = Query("recents", description="Sort mode: 'recents'"),
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    if sort not in ("recents",):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_sort", "detail": "sort must be 'recents'"},
        )
    try:
        return get_library_view(db, user_id, sort=sort)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "db_error", "detail": str(e)})

@router.post("")
async def add_library_route(
    body: dict = Body(...),
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    result = add_library_item(db, user_id, body)

    if "error" in result:
        status = {
            "invalid_input": 400,
            "add_failed": 500,
        }.get(result["error"], 500)
        return JSONResponse(status_code=status, content=result)

    return {"ok": True, **result}

@router.delete("/{kind}/{external_id}")
async def remove_library_route(
    kind: str,
    external_id: str,
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    if kind not in ("album", "playlist"):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_kind", "detail": "kind must be 'album' or 'playlist'"},
        )

    result = remove_library_item(db, user_id, kind, external_id)

    if "error" in result:
        status = {
            "not_found": 404,
            "remove_failed": 500,
        }.get(result["error"], 500)
        return JSONResponse(status_code=status, content=result)

    return {"ok": True, **result}