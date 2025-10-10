# routes/feed.py
from __future__ import annotations

from fastapi import APIRouter, Request
from typing import Any, Dict, List, Optional

from services.feed_source import fetch_most_played_raw, fetch_new_releases_pairs
from services.feed_source import fetch_new_releases_raw_tag_new as _raw_tag_new
from utils.feed_utils import (
    norm as _norm,
    map_album as _map_album,
    map_track as _map_track,
)

from services.feed_repo import list_feed

router = APIRouter(tags=["feed"])

@router.get("/", summary="Feed: most played albums & tracks")
async def get_feed(request: Request):
    albums_raw, songs_raw = fetch_most_played_raw()

    albums: List[Dict[str, Any]] = []
    for it in albums_raw:
        artist = (it.get("artistName") or "").strip()
        title = (it.get("name") or "").strip()
        if not artist or not title:
            continue
        m = _map_album(artist, title)
        if m:
            albums.append(m)

    tracks: List[Dict[str, Any]] = []
    for it in songs_raw:
        artist = (it.get("artistName") or "").strip()
        title = (it.get("name") or "").strip()
        if not artist or not title:
            continue
        m = _map_track(artist, title)
        if m:
            tracks.append(m)

    return {"ok": True, "albums": albums, "tracks": tracks}



@router.get("/new-releases", summary="Feed: new releases (Spotify tag:new → mapped to YT Music)")
async def get_new_releases(store: Optional[str] = None, limit: Optional[int] = None):
    from typing import Any, Dict, List
    from utils.feed_utils import map_albums_until, norm as _norm

    WANT = 25

    # 1) Trae TODOS los pairs de 14 días
    pairs, release_by_key, tracks_by_key = fetch_new_releases_pairs(store=store, limit=limit)
    
    print(f"📊 Total pairs obtenidos: {len(pairs)}")

    # 2) ⚠️ CRÍTICO: Solo intentar mapear los primeros 60-80 pairs (no los 139)
    # Esto da margen para fallos pero no toma 20 minutos
    mapped = map_albums_until(
        [{"artist": a, "title": t} for (a, t) in pairs[:60]],  # ← Límite razonable
        want=WANT,  # ← Parar cuando llegue a 25
        micro_pause=0.3,
    )
    
    print(f"📊 Total mapeados exitosos: {len(mapped)}")

    # 3) Merge + dedup
    albums: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    
    for m in mapped:
        bid = (m.get("id") or "").strip()
        art = (m.get("artist") or "").strip()
        tit = (m.get("title") or "").strip()
        
        if not art or not tit:
            continue
        
        if bid and bid in seen_ids:
            continue
        
        out = dict(m)
        key = _norm(art) + "|" + _norm(tit)
        
        rd = release_by_key.get(key, "")
        if rd:
            out["release_date"] = rd
        
        if not out.get("track_count"):
            tc = tracks_by_key.get(key)
            if isinstance(tc, int):
                out["track_count"] = tc
        
        albums.append(out)
        if bid:
            seen_ids.add(bid)

    # 4) Orden por fecha y corte final
    def _date_key(s: str) -> tuple[int, int, int]:
        try:
            y, m, d = s.split("-")
            return (int(y), int(m), int(d))
        except Exception:
            try:
                y, m = s.split("-")
                return (int(y), int(m), 1)
            except Exception:
                try:
                    return (int(s), 1, 1)
                except Exception:
                    return (0, 0, 0)

    albums.sort(key=lambda a: _date_key(a.get("release_date", "")), reverse=True)
    albums = albums[:WANT]
    
    print(f"📊 Álbumes finales retornados: {len(albums)}")

    return {"ok": True, "new_releases": albums}

@router.get("/most-played", summary="Feed (DB) most_played albums & tracks")
async def get_feed_db(limit: Optional[int] = 25):
    albums = list_feed("most_played", "album", limit or 25)
    tracks = list_feed("most_played", "track", limit or 25)
    return {"ok": True, "albums": albums, "tracks": tracks}

@router.get("/db/new-releases", summary="Feed (DB) new releases")
async def get_new_releases_db(limit: Optional[int] = 25):
    albums = list_feed("new_releases", "album", limit or 25)
    return {"ok": True, "new_releases": albums}