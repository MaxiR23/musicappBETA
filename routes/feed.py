# routes/feed.py
from __future__ import annotations
import os
from fastapi.responses import JSONResponse

from fastapi import APIRouter, Request
from typing import Any, Dict, List, Optional

from services.feed_repo import list_feed
from services.recommendations_repo import list_user_recommendations

from services.cache_service import cached, get_cached, set_cached
from services.cache_config import CacheType, get_all_versions
from scripts.store_user_recommendations import generate_weekly_bucket

router = APIRouter(tags=["feed"])

_RECO_LIMIT_PER_TYPE = int(os.getenv("RECO_LIMIT_PER_TYPE", "20"))


@router.get("/cache/versions", summary="Versiones actuales del caché")
async def get_cache_versions():
    return {
        "ok": True,
        "versions": get_all_versions()
    }


@router.get("/most-played", summary="Feed (DB) most_played albums & tracks")
@cached(CacheType.TOP_ALBUMS)
async def get_feed_db(limit: Optional[int] = 25):
    albums = list_feed("most_played", "album", limit or 25)
    tracks = list_feed("most_played", "track", limit or 25)
    return {"ok": True, "albums": albums, "tracks": tracks}

@router.get("/db/new-releases", summary="Feed (DB) new releases")
@cached(CacheType.NEW_RELEASES)
async def get_new_releases_db(limit: Optional[int] = 25):
    albums = list_feed("new_releases", "album", limit or 25)
    return {"ok": True, "new_releases": albums}

@router.get("/db/new-singles", summary="Feed (DB) singles nuevos")
@cached(CacheType.NEW_SINGLES, ttl=43200)
async def get_new_singles_db(limit: Optional[int] = 25):
    tracks = list_feed("new_singles", "track", limit or 25)
    return {"ok": True, "tracks": tracks}

@router.get("/db/seed-tracks", summary="Feed (DB) seed tracks")
@cached(CacheType.SEED_TRACKS)
async def get_seed_tracks_db(limit: Optional[int] = 25):
    tracks = list_feed("seed_tracks", "track", limit or 25)
    return {"ok": True, "tracks": tracks}

@router.get("/recommendations/me", summary="User recommendations (Bearer auth)")
async def get_user_recommendations_me(
    request: Request,
    bucket: Optional[str] = None,
):
    bucket = bucket or generate_weekly_bucket()
    
    u = getattr(request.state, "user", None) or {}
    user_id = u.get("id")
    
    if not user_id:
        return JSONResponse(
            status_code=401,
            content={"ok": False, "error": "unauthorized"}
        )

    cached_data = get_cached(CacheType.USER_RECOMMENDATIONS, suffix=user_id)
    if cached_data is not None:
        return cached_data

    rows = list_user_recommendations(
        user_id=user_id,
        bucket=bucket,
        item_type=None,
        limit=500,
    )

    artists: List[Dict[str, Any]] = []
    albums:  List[Dict[str, Any]] = []

    for r in rows or []:
        itype   = r.get("item_type")
        iid     = r.get("item_id")
        payload = r.get("payload") or {}

        if itype == "artist":
            item = {"id": iid, **payload}
            if r.get("seed_id"):
                item["similarTo"] = {
                    "id":        r.get("seed_id"),
                    "name":      r.get("seed_name"),
                    "thumbnail": r.get("seed_thumb"),
                }
            artists.append(item)
        elif itype == "album":
            item = {"id": iid, **payload}
            albums.append(item)

    artists = artists[:_RECO_LIMIT_PER_TYPE]
    albums  = albums[:_RECO_LIMIT_PER_TYPE]

    result = {
        "ok": True,
        "bucket": bucket,
        "limit_per_type": _RECO_LIMIT_PER_TYPE,
        "recommendations": {
            "artists": artists,
            "albums":  albums,
        },
    }
    
    set_cached(CacheType.USER_RECOMMENDATIONS, result, suffix=user_id)
    return result

@router.get("/recommendations", summary="User recommendations (by user_id)")
async def get_user_recommendations_db(
    user_id: str,
    bucket: Optional[str] = None,
):
    bucket = bucket or generate_weekly_bucket()
    
    cached_data = get_cached(CacheType.USER_RECOMMENDATIONS, suffix=user_id)
    if cached_data is not None:
        return cached_data

    rows = list_user_recommendations(
        user_id=user_id,
        bucket=bucket,
        item_type=None,
        limit=500,
    ) or []

    artists: List[Dict[str, Any]] = []
    albums:  List[Dict[str, Any]] = []

    for r in rows:
        itype   = r.get("item_type")
        iid     = r.get("item_id")
        payload = r.get("payload") or {}

        if itype == "artist":
            item = {"id": iid, **payload}
            if r.get("seed_id"):
                item["similarTo"] = {
                    "id":        r.get("seed_id"),
                    "name":      r.get("seed_name"),
                    "thumbnail": r.get("seed_thumb"),
                }
            artists.append(item)
        elif itype == "album":
            item = {"id": iid, **payload}
            albums.append(item)

    artists = artists[:_RECO_LIMIT_PER_TYPE]
    albums  = albums[:_RECO_LIMIT_PER_TYPE]

    result = {
        "ok": True,
        "bucket": bucket,
        "limit_per_type": _RECO_LIMIT_PER_TYPE,
        "recommendations": {
            "artists": artists,
            "albums":  albums,
        },
    }
    
    set_cached(CacheType.USER_RECOMMENDATIONS, result, suffix=user_id)
    return result