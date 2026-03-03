# services/feed_source.py
from __future__ import annotations

import os
import requests
from dataclasses import dataclass
from typing import Tuple, List, Dict, Any, Optional, Callable

from services.music_lookup import MusicLookup
from utils.feed_utils import map_track

from utils.feed_utils import norm

import time

from dotenv import load_dotenv
load_dotenv()

FEED_NEW_RELEASES_URL = os.getenv("FEED_NEW_RELEASES_URL")
FEED_CLIENT_ID        = os.getenv("FEED_CLIENT_ID")
FEED_CLIENT_SECRET    = os.getenv("FEED_CLIENT_SECRET")

# Config leída de .env (nombres genéricos, sin mencionar proveedor)
@dataclass(frozen=True)
class FeedConfig:
    store: str = os.getenv("FEED_STORE", "us").strip().lower()
    limit: int = int(os.getenv("FEED_LIMIT", "25"))
    albums_url_tpl: str = os.getenv(
        "FEED_MOST_PLAYED_ALBUMS_URL",
    )
    songs_url_tpl: str = os.getenv(
        "FEED_MOST_PLAYED_SONGS_URL",
    )

CFG = FeedConfig()

def _resolve(url_tpl: str, store: str) -> str:
    # Permite plantillas con {store}
    return url_tpl.format(store=store)

def _grab_json(url: str, timeout: int = 20) -> Dict[str, Any]:
    hdrs = {
        "Accept": "application/json",
        "User-Agent": "feed-agent/1.0",
        "Cache-Control": "no-cache",
    }
    r = requests.get(url, headers=hdrs, timeout=timeout)
    r.raise_for_status()
    return r.json()  # type: ignore[return-value]

def fetch_most_played_raw(cfg: FeedConfig = CFG) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Devuelve listas crudas de 'álbums' y 'songs' del proveedor de feed.
    No hace mapeo a YT Music todavía.
    """
    albums_url = _resolve(cfg.albums_url_tpl, cfg.store)
    songs_url  = _resolve(cfg.songs_url_tpl,  cfg.store)

    albums_feed = _grab_json(albums_url)
    songs_feed  = _grab_json(songs_url)

    # Normalizamos estructura mínima esperada: feed.results[]
    albums = (albums_feed.get("feed") or {}).get("results") or []
    songs  = (songs_feed.get("feed") or {}).get("results") or []

    return albums[: cfg.limit], songs[: cfg.limit]

def _get_feed_token() -> str:
    if not FEED_CLIENT_ID or not FEED_CLIENT_SECRET:
        raise RuntimeError("Config faltante: FEED_CLIENT_ID / FEED_CLIENT_SECRET")
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(FEED_CLIENT_ID, FEED_CLIENT_SECRET),
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]

def fetch_new_releases_raw_tag_new(store: str | None = None, limit: int | None = None) -> Dict[str, Any]:
    """
    Devuelve el JSON crudo de /v1/search?q=tag:new&type=album (no mezcla con 'browse/new-releases').
    Respeta FEED_NEW_RELEASES_URL con {store} y {limit}.
    """
    if not FEED_NEW_RELEASES_URL:
        raise RuntimeError("Config faltante: FEED_NEW_RELEASES_URL")
    st = (store or CFG.store).upper()
    lm = limit or CFG.limit
    url = FEED_NEW_RELEASES_URL.format(store=st, limit=lm)

    tok = _get_feed_token()
    hdrs = {
        "Accept": "application/json",
        "Authorization": f"Bearer {tok}",
        "User-Agent": "feed-agent/1.0",
        "Cache-Control": "no-cache",
    }
    r = requests.get(url, headers=hdrs, timeout=20)
    r.raise_for_status()
    return r.json()

def fetch_new_releases_pairs(
    store: str | None = None,
    limit: int | None = None,
    *,
    on_batch: "Optional[Callable[[List[Tuple[str, str]]], None]]" = None,
    should_stop: "Optional[Callable[[], bool]]" = None,
) -> "Tuple[List[Tuple[str, str]], Dict[str, str], Dict[str, int]]":
    import datetime, requests, re, unicodedata
    from typing import Dict, Any, List, Tuple, Optional, Callable

    country = (store or CFG.store).upper()
    cutoff  = datetime.date.today() - datetime.timedelta(days=14)

    def _parse_date(d: str, p: str):
        try:
            if p == "day":   return datetime.date.fromisoformat(d)
            if p == "month": y, m = d.split("-"); return datetime.date(int(y), int(m), 1)
            if p == "year":  return datetime.date(int(d), 1, 1)
        except Exception:
            return None
        
    tok = _get_feed_token()
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {tok}",
        "User-Agent": "feed-agent/1.0",
        "Cache-Control": "no-cache",
    }

    albums: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    offset, page_size = 0, 50

    # CRÍTICO: Paginar hasta 1000 (no cortar por hit_old_date prematuramente)
    while offset < 1000 and not (should_stop and should_stop()):
        r = requests.get(
            "https://api.spotify.com/v1/search",
            params={"q": "tag:new", "type": "album", "market": country, "limit": page_size, "offset": offset},
            headers=headers, timeout=20,
        )
        r.raise_for_status()
        items = ((r.json() or {}).get("albums") or {}).get("items") or []
        if not items:
            break

        for it in items:
            if (it.get("album_type") or "").lower() != "album":
                continue
            
            rd  = (it.get("release_date") or "").strip()
            rdp = (it.get("release_date_precision") or "").strip()
            d = _parse_date(rd, rdp)
            
            # Solo filtramos por cutoff, NO cortamos el loop completo
            if d and d < cutoff:
                continue  # <- continue en vez de hit_old_date=True

            sid = it.get("id")
            if not sid or sid in seen_ids:
                continue
            
            albums.append(it)
            seen_ids.add(sid)

        if on_batch:
            # Snapshot incremental
            release_by_key: Dict[str, str] = {}
            tracks_by_key: Dict[str, int] = {}
            pairs: List[Tuple[str, str]] = []

            for it in albums:
                title = (it.get("name") or "").strip()
                arts  = it.get("artists") or []
                artist = ", ".join(a.get("name") or "" for a in arts if isinstance(a, dict)).strip()
                if not artist or not title:
                    continue
                key = norm(artist) + "|" + norm(title)

                rd = (it.get("release_date") or "").strip()
                if rd:
                    release_by_key[key] = rd

                tt = it.get("total_tracks")
                if isinstance(tt, int) and tt > 0:
                    tracks_by_key[key] = tt

                pairs.append((artist, title))

            on_batch(pairs)

        if should_stop and should_stop():
            break

        offset += page_size

    # Build final
    release_by_key: Dict[str, str] = {}
    tracks_by_key: Dict[str, int] = {}
    pairs: List[Tuple[str, str]] = []

    for it in albums:
        title = (it.get("name") or "").strip()
        arts  = it.get("artists") or []
        artist = ", ".join(a.get("name") or "" for a in arts if isinstance(a, dict)).strip()
        if not artist or not title:
            continue
        key = norm(artist) + "|" + norm(title)

        rd = (it.get("release_date") or "").strip()
        if rd:
            release_by_key[key] = rd

        tt = it.get("total_tracks")
        if isinstance(tt, int) and tt > 0:
            tracks_by_key[key] = tt

        pairs.append((artist, title))

    return pairs, release_by_key, tracks_by_key

def fetch_new_singles_tracks(store: Optional[str] = None, want: int = 25, pages: int = 4, micro_pause: float = 0.35) -> List[Dict[str, Any]]:
    import datetime

    market = (store or CFG.store).upper()
    cutoff = datetime.date.today() - datetime.timedelta(days=14)

    tok = _get_feed_token()
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {tok}",
        "User-Agent": "feed-agent/1.0",
        "Cache-Control": "no-cache",
    }

    pairs: List[Dict[str, str]] = []
    offset, page_size = 0, 50

    for _ in range(max(1, pages)):
        # URL desde .env (DRY)
        base = FEED_NEW_RELEASES_URL.format(store=market, limit=page_size)
        r = requests.get(base, headers=headers, params={"offset": offset}, timeout=20) 
        r.raise_for_status()
        items = ((r.json() or {}).get("albums") or {}).get("items") or []
        if not items:
            break

        for a in items:
            if int(a.get("total_tracks") or 0) != 1:
                continue
            rd  = (a.get("release_date") or "").strip()
            rdp = (a.get("release_date_precision") or "").strip()
            try:
                if rdp == "day":
                    d = datetime.date.fromisoformat(rd)
                elif rdp == "month":
                    y, m = rd.split("-"); d = datetime.date(int(y), int(m), 1)
                elif rdp == "year":
                    d = datetime.date(int(rd), 1, 1)
                else:
                    d = None
            except Exception:
                d = None
            if d and d < cutoff:
                continue

            title = (a.get("name") or "").strip()
            arts  = a.get("artists") or []
            artist = ", ".join(x.get("name") or "" for x in arts if isinstance(x, dict)).strip()
            if title and artist:
                pairs.append({"artist": artist, "title": title})

        offset += page_size

    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for i, p in enumerate(pairs):
        t = map_track(p["artist"], p["title"])
        if t and (vid := t.get("id")) and vid not in seen:
            out.append(t); seen.add(vid)
            if len(out) >= want:
                break
        if micro_pause and (i % 3 == 2):
            time.sleep(micro_pause)

    return out

def fetch_seed_tracks(limit_pairs: int = 300, want: int = 50, micro_pause: float = 0.35) -> List[Dict[str, Any]]:
    """
    Lee (title, artist) desde la seed (ENV) y devuelve SOLO los tracks mapeados
    con map_track (mismo shape que Apple/Spotify).
    """

    pairs = MusicLookup.get_seed_pairs(limit=limit_pairs)
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for i, p in enumerate(pairs):
        artist = (p.get("artist") or "").strip()
        title  = (p.get("title")  or "").strip()
        if not artist or not title:
            continue

        t = map_track(artist, title)  # payload completo de la canción
        if t and (vid := t.get("id")) and vid not in seen:
            out.append(t)
            seen.add(vid)
            if len(out) >= want:
                break

        if micro_pause and (i % 3 == 2):
            time.sleep(micro_pause)

    return out