# core/rate_limit.py
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from services.auth_utils import get_user_id


def user_id_or_ip(request: Request) -> str:
    """
    Key function para slowapi.
    Prioriza user_id del JWT (per-user, sobrevive NAT/VPN compartido).
    Fallback a IP si no hay auth resuelta.
    """
    try:
        user_id = get_user_id(request)
        if user_id:
            return f"user:{user_id}"
    except Exception:
        pass
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=user_id_or_ip, default_limits=["200/minute"])
