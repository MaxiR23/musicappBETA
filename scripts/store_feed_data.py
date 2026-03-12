"""
Fetch, map y persiste feed data en public.feed_items.

Uso:
    python scripts/store_feed_data.py                          # todos los feeds
    python scripts/store_feed_data.py --only-new-releases      # solo new_releases
    python scripts/store_feed_data.py --only-new-singles --store AR --limit 26
"""
from __future__ import annotations

import argparse
from typing import Any, Dict, List, Optional, Tuple

from services.cache_config import set_manual_version, CacheType
from services.feed_source import (
    CFG,
    fetch_most_played_raw,
    fetch_new_releases_pairs,
    fetch_new_singles_tracks,
    fetch_seed_tracks,
)
from services.feed_repo import replace_feed
from services.supabase_service import supabase_service as sb
from utils.feed_utils import (
    map_album as _map_album,
    map_albums_until,
    map_track as _map_track,
    norm as _norm,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _date_sort_key(date_str: str) -> Tuple[int, int, int]:
    """Parsea YYYY-MM-DD, YYYY-MM o YYYY a tupla ordenable."""
    try:
        parts = date_str.split("-")
        y = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 1
        d = int(parts[2]) if len(parts) > 2 else 1
        return (y, m, d)
    except Exception:
        return (0, 0, 0)

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def build_most_played() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Construye listas de albums y tracks mas reproducidos."""
    albums_raw, songs_raw = fetch_most_played_raw()

    albums: List[Dict[str, Any]] = []
    for it in albums_raw:
        artist = (it.get("artistName") or "").strip()
        title = (it.get("name") or "").strip()
        if not artist or not title:
            continue
        mapped = _map_album(artist, title)
        if mapped:
            albums.append(dict(mapped))

    tracks: List[Dict[str, Any]] = []
    for it in songs_raw:
        artist = (it.get("artistName") or "").strip()
        title = (it.get("name") or "").strip()
        if not artist or not title:
            continue
        mapped = _map_track(artist, title)
        if mapped:
            tracks.append(mapped)

    return albums, tracks

def build_new_releases(
    store: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Construye lista de nuevos lanzamientos (albums)."""
    want = limit or CFG.limit

    pairs, release_by_key, _ = fetch_new_releases_pairs(store=store, limit=limit)

    mapped = map_albums_until(
        [{"artist": a, "title": t} for (a, t) in pairs[:60]],
        want=want,
        micro_pause=0.3,
    )

    albums: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()

    for m in mapped:
        bid = (m.get("id") or "").strip()
        artist = (m.get("artist") or "").strip()
        title = (m.get("title") or "").strip()

        if not artist or not title:
            continue
        if bid and bid in seen_ids:
            continue

        out = dict(m)
        key = _norm(artist) + "|" + _norm(title)

        rd = release_by_key.get(key, "")
        if rd:
            out["release_date"] = rd

        albums.append(out)
        if bid:
            seen_ids.add(bid)

    albums.sort(key=lambda a: _date_sort_key(a.get("release_date", "")), reverse=True)
    return albums[:want]


def build_new_singles(
    store: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Construye lista de nuevos singles (tracks)."""
    want = limit or CFG.limit
    return fetch_new_singles_tracks(store=store, want=want)

def build_seed_tracks(want: int) -> List[Dict[str, Any]]:
    """Construye lista de seed tracks para recomendaciones."""
    return fetch_seed_tracks(limit_pairs=max(100, want * 3), want=want)

# ---------------------------------------------------------------------------
# Persist + invalidate
# ---------------------------------------------------------------------------
def persist_most_played(albums: List[Dict[str, Any]], tracks: List[Dict[str, Any]]) -> None:
    """Persiste most_played e invalida caches."""
    replace_feed(db=sb, kind="most_played", media_type="album", items=albums)
    replace_feed(db=sb, kind="most_played", media_type="track", items=tracks)
    set_manual_version(CacheType.TOP_ALBUMS)
    set_manual_version(CacheType.TOP_TRACKS)
    print("  cache invalidado: TOP_ALBUMS, TOP_TRACKS")


def persist_new_releases(albums: List[Dict[str, Any]]) -> None:
    """Persiste new_releases e invalida caches."""
    replace_feed(db=sb, kind="new_releases", media_type="album", items=albums)
    set_manual_version(CacheType.NEW_RELEASES)
    set_manual_version(CacheType.ARTIST_ALBUMS)
    set_manual_version(CacheType.ARTIST_SINGLES)
    print("  cache invalidado: NEW_RELEASES, ARTIST_ALBUMS, ARTIST_SINGLES")

def persist_new_singles(tracks: List[Dict[str, Any]]) -> None:
    """Persiste new_singles e invalida cache."""
    replace_feed(db=sb, kind="new_singles", media_type="track", items=tracks)
    set_manual_version(CacheType.NEW_SINGLES)
    print("  cache invalidado: NEW_SINGLES")

def persist_seed_tracks(tracks: List[Dict[str, Any]]) -> None:
    """Persiste seed_tracks e invalida cache."""
    replace_feed(db=sb, kind="seed_tracks", media_type="track", items=tracks)
    set_manual_version(CacheType.SEED_TRACKS)
    print("  cache invalidado: SEED_TRACKS")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Fetch, map y persiste feed data en public.feed_items"
    )
    p.add_argument("--store", help="Store/country code (e.g., AR, US)")
    p.add_argument("--limit", type=int, help="Max items por feed")
    p.add_argument("--only-most-played", action="store_true")
    p.add_argument("--only-new-releases", action="store_true")
    p.add_argument("--only-new-singles", action="store_true")
    p.add_argument("--only-seed-tracks", action="store_true")
    args = p.parse_args(argv)

    run_all = not any([
        args.only_most_played,
        args.only_new_releases,
        args.only_new_singles,
        args.only_seed_tracks,
    ])

    # --- most_played ---
    if run_all or args.only_most_played:
        print("[feed] building most_played...")
        mp_albums, mp_tracks = build_most_played()
        print(f"  albums={len(mp_albums)} tracks={len(mp_tracks)}")
        persist_most_played(mp_albums, mp_tracks)

    # --- new_releases ---
    if run_all or args.only_new_releases:
        print("[feed] building new_releases...")
        nr_albums = build_new_releases(store=args.store, limit=args.limit)
        print(f"  albums={len(nr_albums)}")
        persist_new_releases(nr_albums)

    # --- new_singles ---
    if run_all or args.only_new_singles:
        print("[feed] building new_singles...")
        ns_tracks = build_new_singles(store=args.store, limit=args.limit)
        print(f"  tracks={len(ns_tracks)}")
        persist_new_singles(ns_tracks)

    # --- seed_tracks ---
    if run_all or args.only_seed_tracks:
        print("[feed] building seed_tracks...")
        seed = build_seed_tracks(want=(args.limit or CFG.limit))
        print(f"  tracks={len(seed)}")
        persist_seed_tracks(seed)

    print("[feed] done.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())