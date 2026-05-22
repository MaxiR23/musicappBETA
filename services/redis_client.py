"""
Redis client singleton.
Centraliza la conexion a Redis para todo el backend.
"""

import os
import redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Devuelve el cliente Redis (lazy singleton)."""
    global _client
    if _client is None:
        _client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD,
            decode_responses=True,
        )
    return _client