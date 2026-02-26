# utils/futures.py
"""
Helpers para manejo de futures (ThreadPoolExecutor).
"""
from concurrent.futures import Future
from typing import TypeVar

T = TypeVar("T")

def safe_result(fut: Future, default: T) -> T:
    """
    Obtiene el resultado de un Future sin explotar.
    Si el Future falló, devuelve default.
    """
    try:
        return fut.result()
    except Exception:
        return default