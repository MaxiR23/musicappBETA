# services/feed_source.py
from __future__ import annotations

import os
import requests
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
load_dotenv()

FEED_NEW_RELEASES_URL = os.getenv("FEED_NEW_RELEASES_URL")
FEED_CLIENT_ID        = os.getenv("FEED_CLIENT_ID")
FEED_CLIENT_SECRET    = os.getenv("FEED_CLIENT_SECRET")

# ⚙️ Config leída de .env (nombres genéricos, sin mencionar proveedor)
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

def fetch_new_releases_pairs(store: str | None = None, limit: int | None = None) -> List[Tuple[str, str]]:
    """
    Devuelve EXACTAMENTE `limit` pares (artist, title) de lanzamientos nuevos
    que sean SOLO álbumes (album_type == "album"), usando:
      1) /v1/search?q=tag:new&type=album  (paginado)
      2) fallback /v1/browse/new-releases  (álbumes curados)
    """
    want = int(limit or CFG.limit)
    country = (store or CFG.store).upper()

    tok = _get_feed_token()
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {tok}",
        "User-Agent": "feed-agent/1.0",
        "Cache-Control": "no-cache",
    }

    albums: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()

    # --- 1) SEARCH tag:new (paginado) ---
    offset = 0
    page_size = 50
    total = None  # no usamos Optional para evitar imports
    while len(albums) < want:
        r = requests.get(
            "https://api.spotify.com/v1/search",
            params={
                "q": "tag:new",
                "type": "album",
                "market": country,
                "limit": page_size,
                "offset": offset,
            },
            headers=headers,
            timeout=20,
        )
        r.raise_for_status()
        data = r.json() or {}
        block = (data.get("albums") or {})
        total = block.get("total", 0)
        items = block.get("items") or []

        for it in items:
            if (it.get("album_type") or "").lower() != "album":
                continue
            sid = it.get("id")
            if not sid or sid in seen_ids:
                continue
            albums.append(it)
            seen_ids.add(sid)
            if len(albums) >= want:
                break

        offset += page_size
        if total is not None and offset >= total:
            break  # no hay más páginas

    # --- 2) Fallback: BROWSE new-releases ---
    if len(albums) < want:
        need = want - len(albums)
        url = "https://api.spotify.com/v1/browse/new-releases"
        while need > 0 and url:
            r = requests.get(
                url,
                params={"country": country, "limit": 50},
                headers=headers,
                timeout=20,
            )
            r.raise_for_status()
            data = r.json() or {}
            block = data.get("albums") or {}
            for it in (block.get("items") or []):
                if (it.get("album_type") or "").lower() != "album":
                    continue
                sid = it.get("id")
                if not sid or sid in seen_ids:
                    continue
                albums.append(it)
                seen_ids.add(sid)
                need -= 1
                if need <= 0:
                    break
            url = block.get("next")

    # --- Mapear a pares (artist, title) ---
    pairs: List[Tuple[str, str]] = []
    for it in albums[:want]:
        title = (it.get("name") or "").strip()
        arts = it.get("artists") or []
        artist = ", ".join(a.get("name") or "" for a in arts if isinstance(a, dict)).strip()
        if artist and title:
            pairs.append((artist, title))

    return pairs