"""
backfill_duration.py

Lee el SQL exportado de Supabase, parsea los registros,
y enriquece metadata con duration_seconds usando _get_duration_fast.

MODO TEST: procesa solo el primer registro y muestra el resultado en consola.
Cuando confirmes que está todo bien, cambiá TEST_MODE = False para correr en los 226.
"""

import re
import json
import time
import sys
import os

# Agrega la raíz del proyecto al path para que funcionen los imports
# desde scripts/ -> ../../ o ajustá según tu estructura
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.clients import _ytmusic_client
from utils.search_parser import _get_duration_fast
from services.supabase_service import supabase_service as sb

# ─────────────────────────────────────────
TEST_MODE = False # <- True = solo muestra en consola, False = procesa los tracks en DB + UPDATE
SQL_FILE  = os.path.join(os.path.dirname(__file__), "play_events_rows.sql")  # <- mismo directorio que el script
SLEEP_BETWEEN_API_CALLS = 2  # segundos entre llamadas reales a la API
# ─────────────────────────────────────────

def parse_sql_inserts(sql_text: str) -> list[dict]:
    """
    Extrae (id, track_id, metadata) de los INSERT de Supabase.
    Supabase exporta todo en un solo INSERT con múltiples VALUES.
    """
    # Busca cada tupla de valores: ('uuid', 'uuid', 'track_id', 'timestamp', '{json}')
    pattern = re.compile(
        r"\('([^']+)',\s*'([^']+)',\s*'([^']+)',\s*'([^']+)',\s*'(\{.*?\})'\)",
        re.DOTALL
    )

    records = []
    for m in pattern.finditer(sql_text):
        record_id  = m.group(1)
        # user_id = m.group(2) # no lo necesitamos
        track_id = m.group(3)
        # played_at = m.group(4) # no lo necesitamos
        metadata_raw = m.group(5)

        try:
            metadata = json.loads(metadata_raw)
        except json.JSONDecodeError:
            print(f"[WARN] No se pudo parsear metadata de id={record_id}, se omite.")
            continue

        records.append({
            "id":       record_id,
            "track_id": track_id,
            "metadata": metadata,
        })

    return records

def enrich_records(records: list[dict]) -> list[dict]:
    """
    Itera los registros, llama a _get_duration_fast por cada track_id
    (con cache en memoria para no repetir llamadas reales),
    y agrega duration_seconds a metadata.
    """
    yt_api = _ytmusic_client()
    enriched = []
    last_api_call_track = set()  # track_ids que ya consultamos a la API

    for i, rec in enumerate(records):
        track_id = rec["track_id"]
        metadata = rec["metadata"].copy()

        # Si ya tiene duration_seconds, skip
        if metadata.get("duration_seconds"):
            print(f"[{i+1}/{len(records)}] {track_id} — ya tiene duration_seconds={metadata['duration_seconds']}, skip.")
            enriched.append({**rec, "metadata": metadata})
            continue

        # _get_duration_fast tiene su propio _DURATION_CACHE interno,
        # así que si el track_id ya fue consultado, devuelve desde cache sin API call.
        # Solo dormimos cuando hacemos una llamada real (track nuevo).
        is_new_track = track_id not in last_api_call_track

        if is_new_track and last_api_call_track:
            # Solo esperamos si NO es el primero y es un track nuevo
            print(f"  ↳ Esperando {SLEEP_BETWEEN_API_CALLS}s para no ser bloqueados...")
            time.sleep(SLEEP_BETWEEN_API_CALLS)

        duration_secondstr, duration_secondsec = _get_duration_fast(yt_api, track_id)
        last_api_call_track.add(track_id)

        if duration_secondsec is not None:
            metadata["duration_seconds"] = duration_secondsec
            print(f"[{i+1}/{len(records)}] {track_id} — '{metadata.get('track_name', '?')}' → {duration_secondstr} ({duration_secondsec}s) ✓")
        else:
            print(f"[{i+1}/{len(records)}] {track_id} — '{metadata.get('track_name', '?')}' → No se pudo obtener duración ✗")

        enriched.append({**rec, "metadata": metadata})

    return enriched

def save_to_db(enriched: list[dict]):
    """Actualiza metadata de cada registro en play_events."""
    ok = 0
    failed = 0
    for rec in enriched:
        if not rec["metadata"].get("duration_seconds"):
            print(f"  [SKIP] {rec['id']} — sin duration_seconds, no se actualiza.")
            continue
        try:
            sb.table("play_events") \
                .update({"metadata": rec["metadata"]}) \
                .eq("id", rec["id"]) \
                .execute()
            print(f"  [DB ✓] {rec['id']} — '{rec['metadata'].get('track_name', '?')}'")
            ok += 1
        except Exception as e:
            print(f"  [DB ✗] {rec['id']} — Error: {e}")
            failed += 1

    print(f"\n✓ Actualizados: {ok} | ✗ Fallidos: {failed}")


def main():
    if not os.path.exists(SQL_FILE):
        print(f"[ERROR] No se encontró el archivo: {SQL_FILE}")
        sys.exit(1)

    with open(SQL_FILE, "r", encoding="utf-8") as f:
        sql_text = f.read()

    records = parse_sql_inserts(sql_text)
    print(f"✓ Parseados {len(records)} registros del SQL.\n")

    if TEST_MODE:
        print("── MODO TEST: procesando solo el primer registro ──\n")
        records = records[:1]

    enriched = enrich_records(records)

    print("\n── RESULTADO ──")
    for rec in enriched:
        print(json.dumps({
            "id":       rec["id"],
            "track_id": rec["track_id"],
            "metadata": rec["metadata"],
        }, ensure_ascii=False, indent=2))

    if TEST_MODE:
        print("\n✓ Test OK. Si el resultado es correcto, cambiá TEST_MODE = False y volvé a correr.")
    else:
        print("\n── GUARDANDO EN DB ──")
        save_to_db(enriched)

if __name__ == "__main__":
    main()