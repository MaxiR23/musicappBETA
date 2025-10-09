# scripts/store_feed_data.py
from __future__ import annotations
from typing import Any, Dict, List, Optional

import argparse
import sys

from services.feed_source import (
    fetch_most_played_raw,
    fetch_new_releases_pairs,
    fetch_new_releases_raw_tag_new as _raw_tag_new,
)
from services.feed_repo import replace_feed
from utils.feed_utils import norm as _norm, map_album as _map_album, map_track as _map_track


def build_most_played() -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
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

    return albums, tracks


def build_new_releases(store: Optional[str], limit: Optional[int]) -> List[Dict[str, Any]]:
    pairs = fetch_new_releases_pairs(store=store, limit=limit)

    # índice (artist|title → release_date) desde Spotify
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

    # mapear a YT Music y deduplicar
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
            continue

        m["release_date"] = release_by_key.get(key, "")
        albums.append(m)
        if bid:
            seen_ids.add(bid)
        seen_keys.add(key)

    # ordenar por release_date desc
    def _date_key(s: str) -> tuple[int, int, int]:
        try:
            y, m, d = s.split("-"); return (int(y), int(m), int(d))
        except Exception:
            try:
                y, m = s.split("-"); return (int(y), int(m), 1)
            except Exception:
                try:
                    return (int(s), 1, 1)
                except Exception:
                    return (0, 0, 0)

    albums.sort(key=lambda a: _date_key(a.get("release_date", "")), reverse=True)
    return albums


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Fetch → map → persist feed data")
    p.add_argument("--store", help="Store/country code for new-releases (e.g., AR, US)", default=None)
    p.add_argument("--limit", help="Max albums for new-releases", type=int, default=None)
    args = p.parse_args(argv)

    print("[feed] building most_played…")
    mp_albums, mp_tracks = build_most_played()
    print(f"[feed] most_played: albums={len(mp_albums)} tracks={len(mp_tracks)}")

    print("[feed] persisting most_played…")
    replace_feed(kind="most_played", media_type="album", items=mp_albums)
    replace_feed(kind="most_played", media_type="track", items=mp_tracks)

    print("[feed] building new_releases…")
    nr_albums = build_new_releases(store=args.store, limit=args.limit)
    print(f"[feed] new_releases: albums={len(nr_albums)}")

    print("[feed] persisting new_releases…")
    replace_feed(kind="new_releases", media_type="album", items=nr_albums)

    print("[feed] done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())