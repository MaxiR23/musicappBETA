"""
backfill_weekly_stats_duration.py

Lee el JSON exportado de user_weekly_stats, enriquece cada track
en el array stats con durationSeconds (antes de thumbnail_url),
y actualiza la DB.

TEST_MODE = True  → muestra el resultado en consola, no toca la DB.
TEST_MODE = False → UPDATE a la DB.
"""

import json
import time
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.clients import _ytmusic_client
from utils.search_parser import _get_duration_fast
from services.supabase_service import supabase_service as sb

# ─────────────────────────────────────────
TEST_MODE = False
JSON_FILE = os.path.join(os.path.dirname(__file__), "user_weekly_stats_rows.json")
SLEEP_BETWEEN_API_CALLS = 2
# ─────────────────────────────────────────

def enrich_stats(stats: list[dict], yt_api) -> list[dict]:
    """Agrega durationSeconds a cada track del array stats."""
    seen = set()
    enriched = []

    for item in stats:
        entity_id = item.get("entity_id")
        if not entity_id:
            enriched.append(item)
            continue

        item = item.copy()

        is_new = entity_id not in seen
        if is_new and seen:
            print(f"  ↳ Esperando {SLEEP_BETWEEN_API_CALLS}s...")
            time.sleep(SLEEP_BETWEEN_API_CALLS)

        _, duration_sec = _get_duration_fast(yt_api, entity_id)
        seen.add(entity_id)

        if duration_sec is not None:
            thumbnail = item.pop("thumbnail_url", None)
            item["durationSeconds"] = duration_sec
            if thumbnail:
                item["thumbnail_url"] = thumbnail
            print(f"  ✓ {entity_id} — '{item.get('display_name', '?')}' → {duration_sec}s")
        else:
            print(f"  ✗ {entity_id} — '{item.get('display_name', '?')}' → no se pudo obtener duración")

        enriched.append(item)

    return enriched

def main():
    if not os.path.exists(JSON_FILE):
        print(f"[ERROR] No se encontró el archivo: {JSON_FILE}")
        sys.exit(1)

    with open(JSON_FILE, "r", encoding="utf-8") as f:
        rows = json.load(f)

    # Filtrar solo entity_type = track
    track_rows = [r for r in rows if r.get("entity_type") == "track"]
    print(f"✓ {len(track_rows)} fila(s) de tipo 'track' encontradas.\n")

    if TEST_MODE:
        print("── MODO TEST: procesando solo la primera fila ──\n")
        track_rows = track_rows[:1]

    yt_api = _ytmusic_client()
    enriched_rows = []

    for row in track_rows:
        print(f"Procesando fila id={row['id']} (week_start={row['week_start']})")
        stats = json.loads(row["stats"]) if isinstance(row["stats"], str) else row["stats"]
        enriched_stats = enrich_stats(stats, yt_api)
        enriched_rows.append({**row, "stats": enriched_stats})

    print("\n── RESULTADO ──")
    for row in enriched_rows:
        print(json.dumps({
            "id": row["id"],
            "week_start": row["week_start"],
            "stats": row["stats"],
        }, ensure_ascii=False, indent=2))

    if TEST_MODE:
        print("\n✓ Test OK. Si está bien, cambiá TEST_MODE = False y volvé a correr.")
    else:
        print("\n── GUARDANDO EN DB ──")
        ok = 0
        failed = 0
        for row in enriched_rows:
            try:
                sb.table("user_weekly_stats") \
                    .update({"stats": row["stats"]}) \
                    .eq("id", row["id"]) \
                    .execute()
                print(f"  [DB ✓] id={row['id']} week_start={row['week_start']}")
                ok += 1
            except Exception as e:
                print(f"  [DB ✗] id={row['id']} — Error: {e}")
                failed += 1

        print(f"\n✓ Actualizados: {ok} | ✗ Fallidos: {failed}")

if __name__ == "__main__":
    main()