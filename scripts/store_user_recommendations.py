# scripts/store_user_recommendations.py
from __future__ import annotations
import argparse
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from services.cache_config import set_manual_version, CacheType
from services.recommendations_seed_service import build_seed_recommendations
from services.recommendations_repo import replace_user_recommendations
from services.users_repo import get_all_user_ids
from services.supabase_service import supabase_service as sb
from utils.recommendation_utils import (
    calc_valid_until, id_any, thumbnails, artist_name, album_title
)

def generate_weekly_bucket() -> str:
    """Genera bucket automático: weekly_2025w44"""
    now = datetime.now()
    year = now.year
    week = now.isocalendar()[1]
    return f"weekly_{year}w{week:02d}"

def cleanup_old_buckets(user_id: str, keep_bucket: str):
    """Borra todos los buckets del usuario EXCEPTO el actual"""
    try:
        sb.table("user_recommendations") \
          .delete() \
          .eq("user_id", user_id) \
          .neq("bucket", keep_bucket) \
          .execute()
    except Exception as e:
        print(f"  Warning: cleanup failed for {user_id} - {e}")

def gather_until(
    user_id: str,
    want_artists: int,
    want_albums: int,
    per_seed: int,
    lookback: int,
    start_per_type: int = 2,
    max_per_type: int = 14,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Amplía per_type (2→4→6…) hasta cumplir objetivos; dedup simple por id."""
    artists: List[Dict[str, Any]] = []
    albums:  List[Dict[str, Any]] = []
    seen_a, seen_al = set(), set()

    per_type = start_per_type
    while (len(artists) < want_artists or len(albums) < want_albums) and per_type <= max_per_type:
        res = build_seed_recommendations(
            user_id=user_id, per_seed=per_seed, per_type=per_type, lookback=lookback
        )
        a_batch = (res.get("recommend") or {}).get("related_artists") or []
        al_batch = (res.get("recommend") or {}).get("related_albums") or []

        for it in a_batch:
            rid = id_any(it)
            if rid and rid not in seen_a and len(artists) < want_artists:
                seen_a.add(rid); artists.append(it)

        for it in al_batch:
            rid = id_any(it)
            if rid and rid not in seen_al and len(albums) < want_albums:
                seen_al.add(rid); albums.append(it)

        per_type += 2

    return artists[:want_artists], albums[:want_albums]

def to_items_for_db(
    artists: List[Dict[str, Any]],
    albums: List[Dict[str, Any]],
    source: str,
    valid_until: Optional[str],
) -> List[Dict[str, Any]]:
    """Mapea a filas de public.user_recommendations (artistas con similarTo, álbum sin)."""
    out: List[Dict[str, Any]] = []
    rank = 1

    for it in artists:
        rid = id_any(it)
        if not rid:
            continue
        st = it.get("similarTo") or {}
        out.append({
            "item_type": "artist",
            "item_id": rid,
            "rank": rank,
            "payload": {
                "name": artist_name(it),
                "subtitle": it.get("subtitle"),
                "thumbnails": thumbnails(it),
            },
            "source": source,
            "valid_until": valid_until,
            "seed_type": "artist" if st.get("id") else None,
            "seed_id": st.get("id"),
            "seed_name": st.get("name"),
            "seed_thumb": st.get("thumbnail"),
        })
        rank += 1

    for it in albums:
        rid = id_any(it)
        if not rid:
            continue
        out.append({
            "item_type": "album",
            "item_id": rid,
            "rank": rank,
            "payload": {
                "title": album_title(it),
                "artistName": it.get("artistName") or it.get("artist"),
                "thumbnails": thumbnails(it),
                "type": it.get("type"),
                "year": it.get("year"),
                "track_count": it.get("track_count"),
                "release_date": it.get("release_date"),
            },
            "source": source,
            "valid_until": valid_until,
        })
        rank += 1

    return out

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Persiste recomendaciones por usuario en public.user_recommendations")
    p.add_argument("--user-id")
    p.add_argument("--all-users", action="store_true")
    p.add_argument("--bucket")
    p.add_argument("--want-artists", type=int, default=10)
    p.add_argument("--want-albums",  type=int, default=10)
    p.add_argument("--per-seed",     type=int, default=5)
    p.add_argument("--lookback",     type=int, default=800)
    p.add_argument("--max-per-type", type=int, default=14)
    p.add_argument("--valid-days",   type=int, default=7)
    p.add_argument("--source",       default="seed_recos_v1")
    args = p.parse_args(argv)

    if args.all_users:
        user_ids = get_all_user_ids()
    elif args.user_id:
        user_ids = [args.user_id]
    else:
        print("Error: specify --user-id or --all-users")
        return 1

    bucket = args.bucket or generate_weekly_bucket()
    valid_until = calc_valid_until(args.valid_days)
    
    print(f"Using bucket: {bucket}")
    print(f"Cleaning old buckets...")
    
    for user_id in user_ids:
        cleanup_old_buckets(user_id, bucket)
    
    print(f"Processing {len(user_ids)} users...")
    
    for user_id in user_ids:
        try:
            artists, albums = gather_until(
                user_id=user_id,
                want_artists=max(0, args.want_artists),
                want_albums=max(0, args.want_albums),
                per_seed=max(1, args.per_seed),
                lookback=max(1, args.lookback),
                start_per_type=2,
                max_per_type=max(2, args.max_per_type),
            )
            items = to_items_for_db(artists, albums, source=args.source, valid_until=valid_until)
            res = replace_user_recommendations(user_id=user_id, bucket=bucket, items=items)
            print(f"{user_id}: {res.get('inserted')} inserted")
        except Exception as e:
            print(f"{user_id}: ERROR - {e}")

    set_manual_version(CacheType.USER_RECOMMENDATIONS)
    print("[recommendations] cache invalidado: USER_RECOMMENDATIONS")        

    return 0

if __name__ == "__main__":
    raise SystemExit(main())