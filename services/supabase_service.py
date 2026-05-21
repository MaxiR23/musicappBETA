# services/supabase_service.py
import os
import atexit
import threading
from collections import OrderedDict
from typing import Optional

from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Clientes globales (uno solo cada uno, no leakean)
supabase_anon: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
supabase_service: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# ---------------------------------------------------------------------------
# Per-user client cache (RLS)
#
# Problema que resuelve:
#   create_client() abre httpx clients internos en cada sub-modulo (postgrest,
#   auth, storage, functions). Cada uno reserva 2-3 FDs (SSL + pool). Bajo
#   carga, crear un client nuevo por request -> OSError [Errno 24].
#
# Por que cache por JWT y no client global compartido:
#   client.postgrest.auth(jwt) MUTA el client. Si compartimos uno global y dos
#   requests concurrentes mutan el header con JWTs distintos, la 2da query
#   puede salir con el JWT de otro usuario -> bug RLS de seguridad.
#
# Diseno:
#   - OrderedDict por JWT, capped a _CACHE_SIZE.
#   - Eviction LRU: el mas viejo se cierra (libera FDs).
#   - threading.Lock para insert/evict atomico (sync FastAPI corre en
#     threadpool, hay concurrencia real).
#   - atexit handler cierra todo al shutdown.
# ---------------------------------------------------------------------------

_CACHE_SIZE = int(os.getenv("SUPABASE_USER_CLIENT_CACHE_SIZE", "256"))
_ANON_KEY = "__anon__"

_user_client_cache: "OrderedDict[str, Client]" = OrderedDict()
_cache_lock = threading.Lock()


def _close_client(client: Optional[Client]) -> None:
    """Cierra los httpx sessions internos del client. Best-effort."""
    if client is None:
        return
    for sub_name in ("postgrest", "auth", "storage", "functions"):
        try:
            sub = getattr(client, sub_name, None)
            if sub is None:
                continue
            session = getattr(sub, "session", None)
            if session is not None and hasattr(session, "close"):
                session.close()
        except Exception:
            pass


def db_as_user(jwt: str) -> Client:
    """
    Devuelve un cliente autenticado como el usuario del JWT (RLS ON).
    Cacheado por JWT con eviction LRU para evitar leak de FDs.

    Misma signature que antes -> no requiere cambios en call sites.
    """
    key = jwt if jwt else _ANON_KEY

    with _cache_lock:
        # cache hit: move-to-end y devolver
        if key in _user_client_cache:
            _user_client_cache.move_to_end(key)
            return _user_client_cache[key]

        # cache miss: crear, registrar, evictar si excede
        client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        if jwt:
            client.postgrest.auth(jwt)

        _user_client_cache[key] = client

        while len(_user_client_cache) > _CACHE_SIZE:
            _, evicted = _user_client_cache.popitem(last=False)
            _close_client(evicted)

        return client


def _shutdown_cache() -> None:
    """Cierra todos los clients cacheados al shutdown del proceso."""
    with _cache_lock:
        while _user_client_cache:
            _, client = _user_client_cache.popitem(last=False)
            _close_client(client)
    _close_client(supabase_anon)
    _close_client(supabase_service)


atexit.register(_shutdown_cache)