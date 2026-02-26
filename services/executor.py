# services/executor.py
"""
Ejecución concurrente de tareas.
Permite ejecutar múltiples funciones en paralelo y obtener sus resultados.
Útil para reducir latencia cuando hay que hacer varios fetches independientes.
Basado en: https://docs.python.org/3/library/concurrent.futures.html
"""
from concurrent.futures import ThreadPoolExecutor

_EXECUTOR = ThreadPoolExecutor(max_workers=8)

def gather(tasks: dict, timeout: float = 3.0) -> dict:
    """
    Ejecuta funciones en paralelo, devuelve resultados.
    
    Uso:
        results = gather({
            "tracks": lambda: get_tracks(id),
            "albums": lambda: get_albums(id),
        })
    """
    futures = {name: _EXECUTOR.submit(fn) for name, fn in tasks.items()}
    results = {}
    for name, fut in futures.items():
        try:
            results[name] = fut.result(timeout=timeout)
        except Exception:
            results[name] = None
    return results