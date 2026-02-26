# services/events_service.py

## Objetivo
Consultar eventos próximos de un artista por nombre, cachearlos y permitir “cache-only”.
Incluye refresh en background.

## Funciones (API pública)

### get_events_by_artist_name(artist_name: str, limit: int = 10, use_cache: bool = True) -> list
- Valida input vacío => []
- cache key: artist_name.lower().strip()
- si hay cache (CacheType.EVENTS) y cached["events"] => devuelve hasta limit
- si no, llama fetch_upcoming_events_by_artist(..., headliner_only=False)
- guarda en cache y devuelve events[:limit]
- si result trae attractionId => cachea también con suffix "aid:<id>"
- si fetch devuelve no-dict => []

### get_events_cached_only(artist_name: str, limit: int = 10) -> list
- No hace fetch.
- Solo lee cache (CacheType.EVENTS).

### schedule_events_refresh(artist_name: str) -> None
- No bloquea: dispara get_events_by_artist_name(... use_cache=False) en executor.