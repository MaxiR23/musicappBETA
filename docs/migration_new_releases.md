# Migración: New Releases desde upcoming_releases

## Contexto

New releases dejó de generarse desde un pipeline externo (`store_feed_data.py` → `feed_current`). Ahora se leen directamente de la tabla `upcoming_releases`, donde el cron `check_releases.py` ya marca albums como `released` cuando salen.

New singles queda temporalmente deshabilitado en todos los archivos (comentado, no borrado).

---

## Archivos modificados

### 1. `scripts/store_feed_data.py`

| Qué cambió | Detalle |
|---|---|
| `build_new_releases` + `persist_new_releases` | **Borrados** — ya no se generan desde acá |
| `build_new_singles` + `persist_new_singles` | **Comentados** — temporalmente deshabilitado |
| Flag `--only-new-releases` | **Borrado** del CLI |
| Flag `--only-new-singles` | **Comentado** |
| Import `fetch_new_releases_pairs` | **Borrado** |
| Import `map_albums_until` | **Borrado** |
| Import `norm as _norm` | **Borrado** (quedaba huérfano) |
| Helper `_date_sort_key` | **Borrado** (solo lo usaba new_releases) |

El script ahora solo corre `most_played` y `seed_tracks`.

---

### 2. `.github/workflows/update-feed.yml`

| Qué cambió | Detalle |
|---|---|
| Job `update-new-releases` | **Borrado** entero (corría `--only-new-releases --only-new-singles`) |
| Cron `'0 5 * * 1,3,5,0'` | **Borrado** (disparaba ese job) |

Secrets que ya no se usan: `FEED_NEW_RELEASES_URL`, `FEED_STORE`, `FEED_LIMIT`. Se pueden limpiar desde GitHub Settings cuando se quiera.

---

### 3. `services/cache_config.py`

| Qué cambió | Detalle |
|---|---|
| `CacheType.NEW_SINGLES` | **Comentado** en el enum |
| `CACHE_SCHEDULE[NEW_RELEASES]` | Cambiado de `TWICE_WEEKLY` a `MANUAL` |
| `CACHE_SCHEDULE[NEW_SINGLES]` | **Comentado** |
| `DEFAULT_TTL[NEW_SINGLES]` | **Comentado** |
| `invalidate_related_caches("new_release")` | **Comentado** `ARTIST_SINGLES` (no aplica para albums) |

La invalidación de `NEW_RELEASES` ahora es 100% manual vía `set_manual_version`. El TTL de 86400 queda como safety net.

---

### 4. `scripts/check_releases.py`

| Qué cambió | Detalle |
|---|---|
| `invalidate_caches()` | Agregada línea `set_manual_version(CacheType.NEW_RELEASES)` |

Cuando el cron confirma que un album salió, ahora invalida tres cachés:

```python
def invalidate_caches() -> None:
    set_manual_version(CacheType.UPCOMING_RELEASES)
    set_manual_version(CacheType.UPCOMING_ARTIST)
    set_manual_version(CacheType.NEW_RELEASES)
```

---

### 5. `services/new_releases_repo.py` (NUEVO)

Repo separado de `upcoming_releases_repo.py`. Lee de la misma tabla pero con concern distinto.

| Función | Qué hace |
|---|---|
| `build_new_release_item(r)` | Mapper: extrae `album_id`, `release_date`, `artist`, `album`, `thumbnail`, `artist_id` |
| `list_new_releases(db, limit)` | Query: `status = "released"` + `release_date >= hoy - 30 días`, ordenado por `release_date DESC` |
| `list_new_releases_cached(db, limit)` | Versión cacheada con `CacheType.NEW_RELEASES` |

---

### 6. `routes/new_releases.py` (NUEVO)

Endpoint: `GET /api/feed/new-releases`

| Parámetro | Default | Descripción |
|---|---|---|
| `limit` | 30 | Máximo de resultados (1-100) |

Response:

```json
{
  "ok": true,
  "count": 12,
  "releases": [
    {
      "album_id": "MPREb_abc123",
      "release_date": "2026-04-04",
      "artist": "Artista",
      "album": "Nombre del Album",
      "thumbnail": "https://...",
      "artist_id": "UCabc123"
    }
  ]
}
```

Filtra releases sin `thumbnail` o sin `artist_id`.

---

### 7. `app.py`

| Qué cambió | Detalle |
|---|---|
| Import | Agregado `new_releases` en la línea de imports de routes |
| Router | Agregado `app.include_router(new_releases.router, prefix="/api/feed/new-releases")` |

---

### 8. `routes/feed.py`

| Qué cambió | Detalle |
|---|---|
| Endpoint `GET /feed/db/new-releases` | **Borrado** — reemplazado por la route nueva |
| Endpoint `GET /feed/db/new-singles` | **Comentado** — temporalmente deshabilitado |

---

## Flujo completo después de aplicar los cambios

```bash
# 1. Aplicar todos los cambios en el código
# 2. Reiniciar el servicio
sudo systemctl restart beatly

# 3. Verificar que arrancó bien
sudo systemctl status beatly

# 4. Probar el endpoint nuevo
curl -H "Authorization: Bearer TOKEN" \
  https://TU_DOMINIO/api/feed/new-releases
```

---

## Cómo funciona ahora

```
Album anunciado
  → Se agrega a upcoming_releases (status: pending)

Cron 22:00 (check_releases.py)
  → Detecta que el album salió
  → mark_as_released() → status: released + album_id
  → invalidate_caches() → rompe caché de UPCOMING, UPCOMING_ARTIST, NEW_RELEASES

Frontend pide /api/feed/new-releases
  → new_releases_repo lee upcoming_releases WHERE status = released AND últimos 30 días
  → Responde con album_id para navegación

Cron 03:00 (check_releases.py --fallback)
  → Lo que no salió → mark_as_postponed()
  → Invalida cachés
```

---

## Código muerto (limpiar cuando se quiera)

| Archivo | Qué sobra |
|---|---|
| `services/feed_repo.py` | `list_new_releases_for_artist()` y el branch `"new_releases"` en `list_feed()` |
| `services/feed_source.py` | `fetch_new_releases_pairs()` y `fetch_new_singles_tracks()` (si no los usa nadie más) |
| `utils/feed_utils.py` | `map_albums_until()` (si no la usa nadie más) |
| GitHub Secrets | `FEED_NEW_RELEASES_URL`, `FEED_STORE`, `FEED_LIMIT` |