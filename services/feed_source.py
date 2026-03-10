from __future__ import annotations

import datetime
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

from shared.clients import _ytmusic_client
from utils.feed_utils import map_track, norm

load_dotenv()

FEED_NEW_RELEASES_URL = os.getenv("FEED_NEW_RELEASES_URL")
FEED_CLIENT_ID = os.getenv("FEED_CLIENT_ID")
FEED_CLIENT_SECRET = os.getenv("FEED_CLIENT_SECRET")

@dataclass(frozen=True)
class FeedConfig:
    store: str = os.getenv("FEED_STORE", "us").strip().lower()
    limit: int = int(os.getenv("FEED_LIMIT", "25"))
    albums_url_tpl: str = os.getenv("FEED_MOST_PLAYED_ALBUMS_URL", "")
    songs_url_tpl: str = os.getenv("FEED_MOST_PLAYED_SONGS_URL", "")

CFG = FeedConfig()

# ── LÓGICA PURA ──────────────────────────────────────────
def _resolve(url_tpl: str, store: str) -> str:
    return url_tpl.format(store=store)

def _parse_date(d: str, precision: str) -> datetime.date | None:
    try:
        if precision == "day":
            return datetime.date.fromisoformat(d)
        if precision == "month":
            y, m = d.split("-")
            return datetime.date(int(y), int(m), 1)
        if precision == "year":
            return datetime.date(int(d), 1, 1)
    except Exception:
        pass
    return None

def _extract_artist_name(artists: list) -> str:
    return ", ".join(a.get("name") or "" for a in artists if isinstance(a, dict)).strip()

def _is_recent(release_date: str, precision: str, cutoff: datetime.date) -> bool:
    d = _parse_date(release_date, precision)
    if not d:
        return True  # Si no podemos parsear, incluir
    return d >= cutoff

def _build_pair_key(artist: str, title: str) -> str:
    return norm(artist) + "|" + norm(title)

def _album_to_pair(item: Dict[str, Any]) -> Tuple[str, str] | None:
    """Extrae (artist, title) de un album item."""
    title = (item.get("name") or "").strip()
    artist = _extract_artist_name(item.get("artists") or [])
    if not artist or not title:
        return None
    return (artist, title)

def build_pairs_from_albums(
    albums: List[Dict[str, Any]]
) -> Tuple[List[Tuple[str, str]], Dict[str, str], Dict[str, int]]:
    """Construye pairs, release_by_key, tracks_by_key desde albums."""
    release_by_key: Dict[str, str] = {}
    tracks_by_key: Dict[str, int] = {}
    pairs: List[Tuple[str, str]] = []

    for item in albums:
        pair = _album_to_pair(item)
        if not pair:
            continue
        artist, title = pair
        key = _build_pair_key(artist, title)

        rd = (item.get("release_date") or "").strip()
        if rd:
            release_by_key[key] = rd

        tt = item.get("total_tracks")
        if isinstance(tt, int) and tt > 0:
            tracks_by_key[key] = tt

        pairs.append((artist, title))

    return pairs, release_by_key, tracks_by_key

def filter_albums_by_type_and_date(
    items: List[Dict[str, Any]],
    cutoff: datetime.date,
    album_type: str = "album"
) -> List[Dict[str, Any]]:
    """Filtra albums por tipo y fecha."""
    result = []
    for item in items:
        if (item.get("album_type") or "").lower() != album_type:
            continue
        rd = (item.get("release_date") or "").strip()
        rdp = (item.get("release_date_precision") or "").strip()
        if not _is_recent(rd, rdp, cutoff):
            continue
        result.append(item)
    return result

def dedupe_tracks(tracks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplica tracks por id."""
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for t in tracks:
        vid = t.get("id")
        if vid and vid not in seen:
            out.append(t)
            seen.add(vid)
    return out

# ── IO (HTTP) ────────────────────────────────────────────
def _grab_json(url: str, timeout: int = 20) -> Dict[str, Any]:
    hdrs = {
        "Accept": "application/json",
        "User-Agent": "feed-agent/1.0",
        "Cache-Control": "no-cache",
    }
    r = requests.get(url, headers=hdrs, timeout=timeout)
    r.raise_for_status()
    return r.json()

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

def _get_feed_headers() -> Dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {_get_feed_token()}",
        "User-Agent": "feed-agent/1.0",
        "Cache-Control": "no-cache",
    }

def fetch_most_played_raw(cfg: FeedConfig = CFG) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Devuelve listas crudas de albums y songs del proveedor de feed."""
    albums_url = _resolve(cfg.albums_url_tpl, cfg.store)
    songs_url = _resolve(cfg.songs_url_tpl, cfg.store)

    albums_feed = _grab_json(albums_url)
    songs_feed = _grab_json(songs_url)

    albums = (albums_feed.get("feed") or {}).get("results") or []
    songs = (songs_feed.get("feed") or {}).get("results") or []

    return albums[:cfg.limit], songs[:cfg.limit]

def fetch_new_releases_raw_tag_new(store: str | None = None, limit: int | None = None) -> Dict[str, Any]:
    """Devuelve el JSON crudo de /v1/search?q=tag:new&type=album."""
    if not FEED_NEW_RELEASES_URL:
        raise RuntimeError("Config faltante: FEED_NEW_RELEASES_URL")
    st = (store or CFG.store).upper()
    lm = limit or CFG.limit
    url = FEED_NEW_RELEASES_URL.format(store=st, limit=lm)

    r = requests.get(url, headers=_get_feed_headers(), timeout=20)
    r.raise_for_status()
    return r.json()

def fetch_new_releases_pairs(
    store: str | None = None,
    limit: int | None = None,
    *,
    on_batch: Optional[Callable[[List[Tuple[str, str]]], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Tuple[List[Tuple[str, str]], Dict[str, str], Dict[str, int]]:
    """Fetcha albums nuevos y devuelve pairs (artist, title)."""
    country = (store or CFG.store).upper()
    cutoff = datetime.date.today() - datetime.timedelta(days=14)
    headers = _get_feed_headers()

    albums: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    offset, page_size = 0, 50

    while offset < 1000 and not (should_stop and should_stop()):
        r = requests.get(
            "https://api.spotify.com/v1/search",
            params={"q": "tag:new", "type": "album", "market": country, "limit": page_size, "offset": offset},
            headers=headers,
            timeout=20,
        )
        r.raise_for_status()
        items = ((r.json() or {}).get("albums") or {}).get("items") or []
        if not items:
            break

        filtered = filter_albums_by_type_and_date(items, cutoff)
        for item in filtered:
            sid = item.get("id")
            if sid and sid not in seen_ids:
                albums.append(item)
                seen_ids.add(sid)

        if on_batch:
            pairs, _, _ = build_pairs_from_albums(albums)
            on_batch(pairs)

        if should_stop and should_stop():
            break

        offset += page_size

    return build_pairs_from_albums(albums)

def fetch_new_singles_tracks(
    store: Optional[str] = None,
    want: int = 25,
    pages: int = 4,
    micro_pause: float = 0.35
) -> List[Dict[str, Any]]:
    """Fetcha singles nuevos y los mapea a tracks."""
    market = (store or CFG.store).upper()
    cutoff = datetime.date.today() - datetime.timedelta(days=14)
    headers = _get_feed_headers()

    pairs: List[Dict[str, str]] = []
    offset, page_size = 0, 50

    for _ in range(max(1, pages)):
        base = FEED_NEW_RELEASES_URL.format(store=market, limit=page_size)
        r = requests.get(base, headers=headers, params={"offset": offset}, timeout=20)
        r.raise_for_status()
        items = ((r.json() or {}).get("albums") or {}).get("items") or []
        if not items:
            break

        for a in items:
            if int(a.get("total_tracks") or 0) != 1:
                continue
            rd = (a.get("release_date") or "").strip()
            rdp = (a.get("release_date_precision") or "").strip()
            if not _is_recent(rd, rdp, cutoff):
                continue

            title = (a.get("name") or "").strip()
            artist = _extract_artist_name(a.get("artists") or [])
            if title and artist:
                pairs.append({"artist": artist, "title": title})

        offset += page_size

    out: List[Dict[str, Any]] = []
    for i, p in enumerate(pairs):
        t = map_track(p["artist"], p["title"])
        if t:
            out.append(t)
            if len(out) >= want:
                break
        if micro_pause and (i % 3 == 2):
            time.sleep(micro_pause)

    return dedupe_tracks(out)

def fetch_seed_tracks(limit_pairs: int = 300, want: int = 50, micro_pause: float = 0.35) -> List[Dict[str, Any]]:
    """Lee tracks desde la seed playlist y los mapea."""
    raw = _ytmusic_client().get_watch_playlist(
        playlistId=os.getenv("FEED_MUSIC_RELEASE_PLAYLIST_ID"),
        limit=limit_pairs
    ) or {}
    tracks_raw = raw.get("tracks") or []

    pairs = []
    for t in tracks_raw:
        title = (t.get("title") or "").strip()
        artist = _extract_artist_name(t.get("artists") or [])
        if title and artist:
            pairs.append({"title": title, "artist": artist})

    out: List[Dict[str, Any]] = []
    for i, p in enumerate(pairs):
        artist = p.get("artist", "").strip()
        title = p.get("title", "").strip()
        if not artist or not title:
            continue

        t = map_track(artist, title)
        if t:
            out.append(t)
            if len(out) >= want:
                break

        if micro_pause and (i % 3 == 2):
            time.sleep(micro_pause)

    return dedupe_tracks(out)