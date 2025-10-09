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
    # 1) Trae pares (artist, title) ya filtrados a álbumes y con cantidad exacta pedida
    pairs = fetch_new_releases_pairs(store=store, limit=limit)

    # 2) Índice (artist|title → release_date) desde Spotify
    raw = _raw_tag_new(store=store, limit=max(40, (limit or 25)))
    raw_items = ((raw or {}).get("albums") or {}).get("items") or []
    release_by_key: Dict[str, str] = {}
    for it in raw_items:
        if (it.get("album_type") or "").lower() != "album":
            continue
        title = (it.get("name") or "").strip()
        arts = it.get("artists") or []
        artist = ", ".join(a.get("name") or "" for a in arts if isinstance(a, dict)).strip()
        if not artist or not title:
            continue
        key = _norm(artist) + "|" + _norm(title)
        release_by_key[key] = it.get("release_date") or ""

    # 3) Mapear a YT Music y deduplicar por browseId y (artist,title) normalizados
    albums: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()

    for artist, title in pairs:
        m = _map_album(artist, title)
        if not m:
            continue

        bid = m.get("id") or ""
        key = _norm(m.get("artist", artist)) + "|" + _norm(m.get("title", title))
        if (bid and bid in seen_ids) or key in seen_keys:
            continue  # evita duplicados

        # Adjuntar release_date desde Spotify si lo tenemos
        m["release_date"] = release_by_key.get(key, "")  # YYYY, YYYY-MM o YYYY-MM-DD

        albums.append(m)
        if bid:
            seen_ids.add(bid)
        seen_keys.add(key)

    # 4) Ordenar por release_date desc (más nuevo primero). Fechas faltantes al final.
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