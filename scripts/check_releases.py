"""
Confirma o posterga upcoming releases del dia.

Uso:
  python scripts/check_releases.py          # Check 22:00
  python scripts/check_releases.py --fallback  # Fallback 03:00

Crontab:
  0 22 * * * cd /ruta/al/proyecto && python scripts/check_releases.py
  0 3  * * * cd /ruta/al/proyecto && python scripts/check_releases.py --fallback
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.supabase_service import supabase_service as sb
from services.cache_config import CacheType, set_manual_version
from services.upcoming_releases_repo import get_todays_pending, mark_as_released, mark_as_postponed
from shared.clients import _ytmusic_client

DELAY_BETWEEN_CALLS = 3

def check_if_released(artist_id: str, album_name: str) -> str | None:
    """
    Verifica si el album ya salio comparando con el ultimo album del artista.
    Retorna el album_id (browseId) si matchea, None si no.
    """
    if not artist_id or not album_name:
        return None
    try:
        artist_data = _ytmusic_client().get_artist(artist_id)
        albums = artist_data.get("albums", {}).get("results", [])
        if not albums:
            return None

        latest = albums[0]
        latest_title = (latest.get("title") or "").strip().lower()
        target_title = album_name.strip().lower()

        if latest_title != target_title:
            return None

        return latest.get("browseId")
    except Exception as e:
        print(f"  [ERROR] {artist_id}: {e}")
        return None

def invalidate_caches() -> None:
    set_manual_version(CacheType.UPCOMING_RELEASES)
    set_manual_version(CacheType.UPCOMING_ARTIST)
    set_manual_version(CacheType.NEW_RELEASES)

def run_check() -> None:
    """22:00 -- chequea si los releases de hoy ya salieron."""
    pending = get_todays_pending(sb)
    if not pending:
        print("[check_releases] No hay releases pending para hoy.")
        return

    print(f"[check_releases] {len(pending)} releases pending.")
    released_count = 0

    for i, r in enumerate(pending):
        name = f"{r.get('artist_name', '???')} - {r.get('album_name', '???')}"
        print(f"  [{i + 1}/{len(pending)}] {name}")

        if not r.get("artist_id"):
            print("    Sin artist_id, salteo.")
            continue

        album_id = check_if_released(r["artist_id"], r["album_name"])

        if album_id:
            mark_as_released(sb, r["id"], album_id=album_id)
            released_count += 1
            print(f"    RELEASED (album_id: {album_id})")
        else:
            print("    Todavia no salio.")

        if i < len(pending) - 1:
            time.sleep(DELAY_BETWEEN_CALLS)

    if released_count > 0:
        invalidate_caches()
    print(f"\n[check_releases] {released_count}/{len(pending)} confirmados.")

def run_fallback() -> None:
    """03:00 -- marca postponed lo que quede pending."""
    pending = get_todays_pending(sb)
    if not pending:
        print("[check_releases][fallback] No hay releases pending para hoy.")
        return

    print(f"[check_releases][fallback] {len(pending)} siguen pending.")
    for r in pending:
        mark_as_postponed(sb, r["id"])
        print(f"  POSTPONED: {r.get('artist_name', '???')} - {r.get('album_name', '???')}")

    invalidate_caches()
    print(f"\n[check_releases][fallback] {len(pending)} marcados postponed.")

def main():
    parser = argparse.ArgumentParser(description="Check upcoming releases")
    parser.add_argument("--fallback", action="store_true", help="Modo 03:00")
    args = parser.parse_args()
    run_fallback() if args.fallback else run_check()

if __name__ == "__main__":
    main()