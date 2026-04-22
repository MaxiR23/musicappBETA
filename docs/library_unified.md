# Biblioteca unificada

## Contexto

Antes del refactor, la pantalla "Library" del front consumía **tres endpoints separados**:

- `GET /playlists/` — lista de playlists propias
- `GET /playlists/liked` — detalle de la Liked
- `GET /library/` — items saved (albums + playlists de terceros)

Cada uno tenía su propio cache y su propia invalidación. Resultado: crear una playlist no refrescaba la grilla hasta volver a abrir la app, likear no actualizaba el count de Liked, y guardar un álbum obligaba a un pull-to-refresh. Tres fuentes de verdad, tres caches, cero consistencia.

El refactor introduce **un único endpoint** (`GET /library`) que devuelve la grilla ya ordenada y normalizada, con un cache unificado que se invalida desde los tres services que pueden mutarla.

> DOC: [FastAPI — APIRouter](https://fastapi.tiangolo.com/reference/apirouter/)

---

## Arquitectura

```
Cliente → GET /api/library
             ↓
        routes/library.py
             ↓
    services/library_view_service.py  (orquestador + cache)
             ↓
        ┌────┴────┬────────────┐
        ↓         ↓            ↓
   playlist_  likes_      library_
   service    service     service
   (propias)  (liked)     (saved)
```

**El orquestador no toca DB directamente.** Delega en los services existentes, que tienen sus propios caches de detalle. Solo cachea el resultado unificado (metadata liviana para grilla, sin tracks adentro).

---

## Componentes nuevos

### `services/library_view_cache.py`

Módulo neutro que expone `invalidate_library_view(user_id)`. Existe aparte del `library_view_service` para **romper el ciclo de imports**: los tres services de mutación importan de acá, y `library_view_service` también, pero **nadie importa de ellos**.

```python
from services.cache_service import invalidate
from services.cache_config import CacheType

_KNOWN_SORTS: tuple[str, ...] = ("recents",)

def invalidate_library_view(user_id: str) -> None:
    for sort in _KNOWN_SORTS:
        invalidate(CacheType.LIBRARY_VIEW, suffix=f"{user_id}:{sort}")
```

Cuando agreguemos un nuevo modo de orden (ej. `"alphabetical"`), se suma a `_KNOWN_SORTS` y listo.

> DOC: [Python circular imports — official](https://docs.python.org/3/reference/import.html#package-relative-imports)

### `services/library_view_service.py`

Orquestador. Expone `get_library_view(db, user_id, sort="recents")`. Lee del cache, si hay miss combina las tres fuentes vía los services existentes, normaliza, ordena y cachea.

Shape de salida:

```python
{
  "sort": "recents",
  "items": [
    {"kind": "liked",          "id": "liked",        "title": "Liked Songs", "thumbnail_url": "...", "subtitle": "N tracks", "sorted_at": ""},
    {"kind": "own_playlist",   "id": "<uuid>",       "title": "...",         "thumbnail_url": "...", "subtitle": "",         "sorted_at": "..."},
    {"kind": "saved_album",    "id": "<ext_id>",     "title": "...",         "thumbnail_url": "...", "subtitle": "<artist>", "sorted_at": "..."},
    {"kind": "saved_playlist", "id": "<ext_id>",     "title": "...",         "thumbnail_url": "...", "subtitle": "<artist>", "sorted_at": "..."}
  ]
}
```

### `CacheType.LIBRARY_VIEW`

Nuevo tipo de cache con schedule `MANUAL` y TTL 3600s. Reemplaza al viejo `CacheType.LIBRARY` (borrado) y al uso del viejo `USER_PLAYLISTS:{user_id}` para la lista (el uso para detalle `USER_PLAYLISTS:{playlist_id}:{user_id}` sigue vivo).

---

## Regla de orden

| Posición | Qué va |
|---|---|
| Primera | `kind == "liked"` (siempre, invariante) |
| Resto | Mezclado por `sorted_at desc` |

El campo `sorted_at` es `created_at` para playlists propias y `added_at` para items saved. La Liked no participa del sort (siempre pineada arriba).

---

## Invalidación cruzada

Las mutaciones en los tres services llaman a `invalidate_library_view(user_id)`:

| Acción | Service | Qué invalida |
|---|---|---|
| Crear/editar/borrar playlist | `playlist_service` | `LIBRARY_VIEW` + detalle de la playlist |
| Agregar/quitar track de playlist | `playlist_service` | `LIBRARY_VIEW` + detalle |
| Like/unlike track | `likes_service` | `LIBRARY_VIEW` + `LIKED_TRACKS` |
| Save/unsave album o playlist externa | `library_service` | `LIBRARY_VIEW` |

Los caches de **detalle** (`USER_PLAYLISTS:{id}:{user_id}` y `LIKED_TRACKS:{user_id}`) sobreviven sin cambios — se usan al abrir una playlist con sus tracks.

---

## Endpoints

### Nuevos

| Método | Ruta | Qué hace |
|---|---|---|
| `GET` | `/api/library?sort=recents` | Grilla unificada |

### Eliminados

| Método | Ruta | Reemplazo |
|---|---|---|
| `GET` | `/api/playlists/` | `GET /api/library` filtrado por `kind == "own_playlist"` |
| `GET` | `/api/library/` (viejo shape) | `GET /api/library` unificado |

### Intactos

| Método | Ruta | Propósito |
|---|---|---|
| `GET` | `/api/playlists/{id}` | Detalle de playlist con tracks |
| `GET` | `/api/playlists/liked` | Detalle de Liked con tracks |
| `POST/PATCH/DELETE` | `/api/playlists/*` | Mutaciones de playlists |
| `POST/DELETE` | `/api/library/*` | Save/unsave |
| `POST/DELETE` | `/api/likes/*` | Like/unlike |

---

## Decisión de diseño: VIEW en Postgres vs Python

Se evaluó crear una VIEW en Postgres que hiciera `UNION ALL` de las tres tablas. Se descartó porque:

- Duplica lógica entre SQL y Python (cada cambio de shape = migración).
- Los services existentes ya cachean lo suyo; el orquestador se aprovecha de esos caches en cascada.
- Testing y debugging más simples con lógica en Python.
- La VIEW queda como opción futura si se necesita optimizar, sin romper el patrón actual.

---

## Trailing slash redirect

Los routers `GET/POST` que antes eran `@router.get("/")` se cambiaron a `@router.get("")` para evitar el redirect `307` que forzaba dos requests. Ahora `GET /api/library` responde `200` directo sin rebote.

> DOC: [Starlette — redirect_slashes](https://www.starlette.io/routing/#trailing-slashes)

---

## Resumen de archivos tocados

```
backend/
├── services/
│   ├── cache_config.py           ← agregado CacheType.LIBRARY_VIEW, borrado LIBRARY
│   ├── library_view_cache.py     ← NUEVO: invalidador neutro sin ciclos
│   ├── library_view_service.py   ← NUEVO: orquestador + cache unificado
│   ├── playlist_service.py       ← sacado cache de lista, invalida LIBRARY_VIEW
│   ├── likes_service.py          ← invalida LIBRARY_VIEW en like/unlike
│   └── library_service.py        ← sacado cache propio, invalida LIBRARY_VIEW
└── routes/
    ├── library.py                ← GET /library nuevo, trailing slash fix
    └── playlists.py              ← borrado GET /, trailing slash fix
```

> DOC: [FastAPI — Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/)