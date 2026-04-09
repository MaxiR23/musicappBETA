from __future__ import annotations
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from core.dependencies import get_db, get_current_user_id
from services.db_protocol import DBClient
from services.feed_repo import list_feed
from services.recommendations_repo import list_user_recommendations
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType, get_all_versions
from scripts.store_user_recommendations import generate_weekly_bucket
from services.replay_service import get_replay_songs
from services.listen_again_service import get_listen_again_cached

router = APIRouter(tags=["feed"])

_RECO_LIMIT_PER_TYPE = int(os.getenv("RECO_LIMIT_PER_TYPE", "20"))

# ── HELPERS ──────────────────────────────────────────────
def _build_recommendations_result(rows: List[Dict[str, Any]], bucket: str) -> Dict[str, Any]:
    """Mapea rows de DB a resultado de recomendaciones."""
    artists: List[Dict[str, Any]] = []
    albums: List[Dict[str, Any]] = []

    for r in rows:
        itype = r.get("item_type")
        iid = r.get("item_id")
        payload = r.get("payload") or {}

        if itype == "artist":
            item = {"id": iid, **payload}
            if r.get("seed_id"):
                item["similar_to"] = {
                    "id":        r.get("seed_id"),
                    "name":      r.get("seed_name"),
                    "thumbnail": r.get("seed_thumb"),
                }
            artists.append(item)
        elif itype == "album":
            albums.append({"id": iid, **payload})

    return {
        "ok": True,
        "bucket": bucket,
        "limit_per_type": _RECO_LIMIT_PER_TYPE,
        "recommendations": {
            "artists": artists[:_RECO_LIMIT_PER_TYPE],
            "albums":  albums[:_RECO_LIMIT_PER_TYPE],
        },
    }

# ── CACHE ────────────────────────────────────────────────
@router.get("/cache/versions", summary="Versiones actuales del caché")
async def get_cache_versions():
    return {"ok": True, "versions": get_all_versions()}

# ── FEED ─────────────────────────────────────────────────
@router.get("/most-played", summary="Feed (DB) most_played albums & tracks")
async def get_feed_db(limit: Optional[int] = 25, db: DBClient = Depends(get_db)):
    cached_data = get_cached(CacheType.TOP_ALBUMS)
    if cached_data is not None:
        return cached_data
    try:
        albums = list_feed(db, "most_played", "album", limit or 25)
        tracks = list_feed(db, "most_played", "track", limit or 25)
        if not albums and not tracks:
            return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})
        result = {"ok": True, "albums": albums, "tracks": tracks}
        set_cached(CacheType.TOP_ALBUMS, result)
        return result
    except Exception as e:
        print(f"[feed][most-played][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})

# --- new_singles (temporalmente deshabilitado) ---
# @router.get("/db/new-singles", summary="Feed (DB) singles nuevos")
# async def get_new_singles_db(limit: Optional[int] = 25, db: DBClient = Depends(get_db)):
#     cached_data = get_cached(CacheType.NEW_SINGLES)
#     if cached_data is not None:
#         return cached_data
#     try:
#         tracks = list_feed(db, "new_singles", "track", limit or 25)
#         if not tracks:
#             return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})
#         result = {"ok": True, "tracks": tracks}
#         set_cached(CacheType.NEW_SINGLES, result, ttl=43200)
#         return result
#     except Exception as e:
#         print(f"[feed][new-singles][ERROR] {e}")
#         return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})

@router.get("/db/seed-tracks", summary="Feed (DB) seed tracks")
async def get_seed_tracks_db(limit: Optional[int] = 25, db: DBClient = Depends(get_db)):
    cached_data = get_cached(CacheType.SEED_TRACKS)
    if cached_data is not None:
        return cached_data
    try:
        tracks = list_feed(db, "seed_tracks", "track", limit or 25)
        if not tracks:
            return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})
        result = {"ok": True, "tracks": tracks}
        set_cached(CacheType.SEED_TRACKS, result)
        return result
    except Exception as e:
        print(f"[feed][seed-tracks][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})

# ── RECOMMENDATIONS ───────────────────────────────────────
@router.get("/recommendations/me", summary="User recommendations (Bearer auth)")
async def get_user_recommendations_me(
    bucket: Optional[str] = None,
    user_id: str = Depends(get_current_user_id),
    db: DBClient = Depends(get_db),
):
    bucket = bucket or generate_weekly_bucket()
    cached_data = get_cached(CacheType.USER_RECOMMENDATIONS, suffix=user_id)
    if cached_data is not None:
        return cached_data
    try:
        rows = list_user_recommendations(db=db, user_id=user_id, bucket=bucket, item_type=None, limit=500) or []
    except Exception as e:
        print(f"[feed][recommendations/me][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})
    result = _build_recommendations_result(rows, bucket)
    set_cached(CacheType.USER_RECOMMENDATIONS, result, suffix=user_id)
    return result

@router.get("/recommendations", summary="User recommendations (by user_id)")
async def get_user_recommendations_db(user_id: str, bucket: Optional[str] = None, db: DBClient = Depends(get_db)):
    bucket = bucket or generate_weekly_bucket()
    cached_data = get_cached(CacheType.USER_RECOMMENDATIONS, suffix=user_id)
    if cached_data is not None:
        return cached_data
    try:
        rows = list_user_recommendations(db=db, user_id=user_id, bucket=bucket, item_type=None, limit=500) or []
    except Exception as e:
        print(f"[feed][recommendations][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})
    result = _build_recommendations_result(rows, bucket)
    set_cached(CacheType.USER_RECOMMENDATIONS, result, suffix=user_id)
    return result

@router.get("/replay")
def replay(user_id: str = Depends(get_current_user_id), db: DBClient = Depends(get_db)):
    try:
        return get_replay_songs(db=db, user_id=user_id)
    except Exception as e:
        print(f"[replay][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})

@router.get("/listen-again")
def listen_again(user_id: str = Depends(get_current_user_id), db: DBClient = Depends(get_db)):
    try:
        result = get_listen_again_cached(db=db, user_id=user_id)
        return {"ok": True, "album": result}
    except Exception as e:
        print(f"[listen-again][ERROR] {e}")
        return JSONResponse(status_code=502, content={"ok": False, "error": "service_unavailable"})