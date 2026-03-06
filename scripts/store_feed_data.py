# scripts/store_feed_data.py
from __future__ import annotations
from typing import Any, Dict, List, Optional

import argparse
import sys

from services.feed_source import (
    fetch_most_played_raw,
    fetch_new_releases_pairs,
    fetch_seed_tracks,
    fetch_new_singles_tracks
)
from services.feed_repo import replace_feed
from services.cache_config import set_manual_version, CacheType
from utils.feed_utils import norm as _norm, map_album as _map_album, map_track as _map_track, map_albums_until

from services.feed_source import CFG

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
            out = dict(m)
            aid = out.get("artist_id")
            if aid:
                out["artist_id"] = aid
            albums.append(out)

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
    WANT = limit or CFG.limit 

    # 1) Trae TODOS los pairs de 14 días + metadata extra
    pairs, release_by_key, tracks_by_key = fetch_new_releases_pairs(store=store, limit=limit)

    # 2) Mapear hasta WANT, con límite razonable de entrada
    mapped = map_albums_until(
        [{"artist": a, "title": t} for (a, t) in pairs[:60]],
        want=WANT,
        micro_pause=0.3,
    )

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
        
        aid = out.get("artist_id")
        if aid:
            out["artist_id"] = aid
        
        key = _norm(art) + "|" + _norm(tit)
        
        # Merge release_date y track_count de Spotify
        rd = release_by_key.get(key, "")
        if rd:
            out["release_date"] = rd
        
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

    return albums

def build_seed_tracks(want: int) -> List[Dict[str, Any]]:
    return fetch_seed_tracks(limit_pairs=max(100, want * 3), want=want)

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Fetch → map → persist feed data")
    p.add_argument("--store", help="Store/country code for new-releases (e.g., AR, US)", default=None)
    p.add_argument("--limit", help="Max albums for new-releases", type=int, default=None)
    
    # Nuevos flags para ejecutar feeds individuales
    p.add_argument("--only-most-played", action="store_true", help="Only update most_played")
    p.add_argument("--only-new-releases", action="store_true", help="Only update new_releases")
    p.add_argument("--only-new-singles", action="store_true", help="Only update new_singles")
    p.add_argument("--only-seed-tracks", action="store_true", help="Only update seed_tracks")
    
    args = p.parse_args(argv)

    # Si no se especifica ningún flag, ejecutar todos (comportamiento original)
    run_all = not any([
        args.only_most_played,
        args.only_new_releases,
        args.only_new_singles,
        args.only_seed_tracks
    ])

    if run_all or args.only_most_played:
        print("[feed] building most_played…")
        mp_albums, mp_tracks = build_most_played()
        print(f"[feed] most_played: albums={len(mp_albums)} tracks={len(mp_tracks)}")
        print("[feed] persisting most_played…")
        replace_feed(kind="most_played", media_type="album", items=mp_albums)
        replace_feed(kind="most_played", media_type="track", items=mp_tracks)
        
        # Invalidar cachés relacionados
        set_manual_version(CacheType.TOP_ALBUMS)
        set_manual_version(CacheType.TOP_TRACKS)
        print("[feed] caches invalidados: TOP_ALBUMS, TOP_TRACKS")

    if run_all or args.only_new_releases:
        print("[feed] building new_releases…")
        nr_albums = build_new_releases(store=args.store, limit=args.limit)
        print(f"[feed] new_releases: albums={len(nr_albums)}")
        print("[feed] persisting new_releases…")
        replace_feed(kind="new_releases", media_type="album", items=nr_albums)
        
        # Invalidar cachés relacionados
        set_manual_version(CacheType.NEW_RELEASES)
        set_manual_version(CacheType.ARTIST_ALBUMS)
        set_manual_version(CacheType.ARTIST_SINGLES)
        print("[feed] caches invalidados: NEW_RELEASES, ARTIST_ALBUMS, ARTIST_SINGLES")

    if run_all or args.only_new_singles:
        print("[feed] building new_singles…")
        new_singles = fetch_new_singles_tracks(store=args.store, want=(args.limit or CFG.limit))
        print(f"[feed] new_singles: tracks={len(new_singles)}")
        print("[feed] persisting new_singles…")
        replace_feed(kind="new_singles", media_type="track", items=new_singles)
        
        # Invalidar caché
        set_manual_version(CacheType.NEW_SINGLES)   # new_singles usa el mismo CacheType
        print("[feed] cache invalidado: NEW_SINGLES")

    if run_all or args.only_seed_tracks:
        print("[feed] building seed_tracks…")
        seed_tracks = build_seed_tracks(want=(args.limit or CFG.limit))
        print(f"[feed] seed_tracks: tracks={len(seed_tracks)}")
        print("[feed] persisting seed_tracks…")
        replace_feed(kind="seed_tracks", media_type="track", items=seed_tracks)
        
        # Invalidar caché
        set_manual_version(CacheType.SEED_TRACKS)
        print("[feed] cache invalidado: SEED_TRACKS")

    print("[feed] done.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())