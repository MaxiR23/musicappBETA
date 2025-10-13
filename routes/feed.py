# routes/feed.py
from __future__ import annotations
import os

from fastapi import APIRouter, Request
from typing import Any, Dict, List, Optional

from services.feed_source import fetch_new_releases_raw_tag_new as _raw_tag_new
from services.feed_repo import list_feed
from services.recommendations_repo import list_user_recommendations

router = APIRouter(tags=["feed"])

_RECO_LIMIT_PER_TYPE = int(os.getenv("RECO_LIMIT_PER_TYPE", "20"))

@router.get("/most-played", summary="Feed (DB) most_played albums & tracks")
async def get_feed_db(limit: Optional[int] = 25):
    albums = list_feed("most_played", "album", limit or 25)
    tracks = list_feed("most_played", "track", limit or 25)
    return {"ok": True, "albums": albums, "tracks": tracks}

@router.get("/db/new-releases", summary="Feed (DB) new releases")
async def get_new_releases_db(limit: Optional[int] = 25):
    albums = list_feed("new_releases", "album", limit or 25)
    return {"ok": True, "new_releases": albums}

# routes/feed.py
@router.get("/db/new-singles", summary="Feed (DB) singles nuevos")
async def get_new_singles_db(limit: Optional[int] = 25):
    tracks = list_feed("new_singles", "track", limit or 25)
    return {"ok": True, "tracks": tracks}

@router.get("/db/seed-tracks", summary="Feed (DB) seed tracks")
async def get_seed_tracks_db(limit: Optional[int] = 25):
    tracks = list_feed("seed_tracks", "track", limit or 25)
    return {"ok": True, "tracks": tracks}

#### TESTS 

@router.get("/recommendations", summary="User recommendations (DB): artistas/álbumes")
async def get_user_recommendations_db(
    user_id: str,
    bucket: str = "seed_recos_v1",
):
    """
    Devuelve las recomendaciones guardadas para (user_id, bucket),
    aplicando un límite por tipo definido en el servidor.
    No se expone 'limit' como query param.
    """
    rows = list_user_recommendations(
        user_id=user_id,
        bucket=bucket,
        item_type=None,
        limit=500,  # traemos holgado y recortamos por tipo abajo
    )

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

    # Recorte server-side (no visible en la URL)
    artists = artists[:_RECO_LIMIT_PER_TYPE]
    albums  = albums[:_RECO_LIMIT_PER_TYPE]

    return {
        "ok": True,
        "bucket": bucket,
        "limit_per_type": _RECO_LIMIT_PER_TYPE,
        "recommendations": {
            "artists": artists,
            "albums":  albums,
        },
    }