"""
Fetch, map y persiste feed data en public.feed_items.

Uso:
    python scripts/store_feed_data.py                          # todos los feeds
    python scripts/store_feed_data.py --only-most-played       # solo most_played
    python scripts/store_feed_data.py --only-seed-tracks       # solo seed_tracks
    python scripts/store_feed_data.py --dry-run                # no persiste, muestra 1 row de cada
"""
from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List, Optional, Tuple

from services.cache_config import set_manual_version, CacheType
from services.feed_source import (
    CFG,
    fetch_most_played_raw,
    # fetch_new_singles_tracks,  # temporalmente deshabilitado
    fetch_seed_tracks,
)
from services.feed_repo import replace_feed, build_rows
from services.supabase_service import supabase_service as sb
from utils.feed_utils import (
    map_album as _map_album,
    map_track as _map_track,
    norm as _norm,
)

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


# --- new_singles (temporalmente deshabilitado) ---
# def build_new_singles(
#     store: Optional[str] = None,
#     limit: Optional[int] = None,
# ) -> List[Dict[str, Any]]:
#     """Construye lista de nuevos singles (tracks)."""
#     want = limit or CFG.limit
#     return fetch_new_singles_tracks(store=store, want=want)


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

#TODO: FIX.
# --- new_singles (temporalmente deshabilitado) ---
# def persist_new_singles(tracks: List[Dict[str, Any]]) -> None:
#     """Persiste new_singles e invalida cache."""
#     replace_feed(db=sb, kind="new_singles", media_type="track", items=tracks)
#     set_manual_version(CacheType.NEW_SINGLES)
#     print("  cache invalidado: NEW_SINGLES")

def persist_seed_tracks(tracks: List[Dict[str, Any]]) -> None:
    """Persiste seed_tracks e invalida cache."""
    replace_feed(db=sb, kind="seed_tracks", media_type="track", items=tracks)
    set_manual_version(CacheType.SEED_TRACKS)
    print("  cache invalidado: SEED_TRACKS")

# ---------------------------------------------------------------------------
# Dry-run helper
# ---------------------------------------------------------------------------
def _print_dry_row(label: str, kind: str, media_type: str, items: List[Dict[str, Any]]) -> None:
    if not items:
        print(f"[dry-run] {label}: (sin items)")
        return
    rows = build_rows(kind, media_type, items[:1])
    print(f"[dry-run] {label} sample row:")
    print(json.dumps(rows[0], indent=2, ensure_ascii=False))

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
    # p.add_argument("--only-new-singles", action="store_true")  # temporalmente deshabilitado
    p.add_argument("--only-seed-tracks", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="No persiste, muestra 1 row de cada tipo")
    args = p.parse_args(argv)

    run_all = not any([
        args.only_most_played,
        # args.only_new_singles,
        args.only_seed_tracks,
    ])

    # --- most_played ---
    if run_all or args.only_most_played:
        print("[feed] building most_played...")
        mp_albums, mp_tracks = build_most_played()
        print(f"  albums={len(mp_albums)} tracks={len(mp_tracks)}")
        if args.dry_run:
            _print_dry_row("most_played album", "most_played", "album", mp_albums)
            _print_dry_row("most_played track", "most_played", "track", mp_tracks)
        else:
            persist_most_played(mp_albums, mp_tracks)

    # --- new_singles (temporalmente deshabilitado) ---
    # if run_all or args.only_new_singles:
    #     print("[feed] building new_singles...")
    #     ns_tracks = build_new_singles(store=args.store, limit=args.limit)
    #     print(f"  tracks={len(ns_tracks)}")
    #     persist_new_singles(ns_tracks)

    # --- seed_tracks ---
    if run_all or args.only_seed_tracks:
        print("[feed] building seed_tracks...")
        seed = build_seed_tracks(want=(args.limit or CFG.limit))
        print(f"  tracks={len(seed)}")
        if args.dry_run:
            _print_dry_row("seed_tracks", "seed_tracks", "track", seed)
        else:
            persist_seed_tracks(seed)

    if args.dry_run:
        print("[feed] dry-run done. Nothing was persisted.")
    else:
        print("[feed] done.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())