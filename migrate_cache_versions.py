"""
One-time migration: vuelca cache_versions.json a Redis.
Correr UNA sola vez. Despues borrar el JSON.
"""
import json
from pathlib import Path
from services.redis_client import get_redis

JSON_PATH = Path(__file__).parent / "cache_versions.json"
PREFIX = "cache:manual:"

with open(JSON_PATH) as f:
    versions = json.load(f)

r = get_redis()
for cache_type, version in versions.items():
    key = f"{PREFIX}{cache_type}"
    r.set(key, version)
    print(f"Migrated: {key} -> {version}")

print(f"\nTotal migrado: {len(versions)}")