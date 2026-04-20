from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse

from core.dependencies import get_current_user_id, get_user_db
from services.db_protocol import DBClient
from services.library_service import (
    add_library_item,
    list_library_items,
    remove_library_item,
)

router = APIRouter(tags=["library"])

@router.get("/")
async def list_library_route(
    kind: str | None = Query(None, description="Filter by 'album' or 'playlist'"),
    db: DBClient = Depends(get_user_db),
    user_id: str = Depends(get_current_user_id),
):
    if kind is not None and kind not in ("album", "playlist"):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_kind", "detail": "kind must be 'album' or 'playlist'"},
        )
    try:
        items = list_library_items(db, user_id, kind)
        return {"items": items}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "db_error", "detail": str(e)})

@router.post("/")
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