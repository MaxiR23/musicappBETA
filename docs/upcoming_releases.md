# Upcoming Releases — Sistema completo

## Qué logré

Implementamos un sistema de **upcoming releases** end-to-end: desde la tabla en Supabase hasta la sección en el Home del frontend, con un sistema de estados (`pending` → `released` / `postponed`), check en tiempo real cuando un usuario visita un artista, y un cron como red de seguridad.

---

## Arquitectura

```
DB (upcoming_releases)
  ↓
Repo (upcoming_releases_repo.py)     ← queries filtradas por status=pending
  ↓
Endpoint (routes/upcoming_releases)  ← GET /upcoming-releases, GET /upcoming-releases/next
  ↓
Frontend (musicService → useHomeFeed → HomeScreen)
  ↓
Sección "Próximos lanzamientos" en Home + FeedListScreen con "ver más"
```

```
Confirmación de releases:

1. Tiempo real (artist_service.get_artist)
   → compara último album del artista con upcoming pending
   → si matchea → mark_as_released + invalidar caches

2. Cron (scripts/check_releases.py)
   → 22:00: chequea si los releases de hoy ya salieron
   → 03:00: marca postponed los que quedan pending
```

---

## Tabla

```sql
create table public.upcoming_releases (
  id             uuid        not null default gen_random_uuid(),
  artist_name    text        not null,
  artist_id      text        null,
  album_name     text        not null,
  release_date   date        null,
  is_tba         boolean     null default false,
  label          text        null,
  thumbnail_url  text        null,
  track_count    integer     null,
  status         text        not null default 'pending',
  confirmed_at   timestamptz null,
  created_at     timestamptz null default now(),
  updated_at     timestamptz null default now(),
  constraint upcoming_releases_pkey primary key (id)
);
```

### Índices

```sql
create index idx_upcoming_releases_date on public.upcoming_releases (release_date)
  where release_date is not null;

create index idx_upcoming_releases_tba on public.upcoming_releases (is_tba)
  where is_tba = true;

create index idx_upcoming_releases_artist_name on public.upcoming_releases (artist_name);

create index idx_upcoming_releases_status on public.upcoming_releases (status)
  where status = 'pending';
```

### Estados

| Status | Significado |
|---|---|
| `pending` | Todavía no salió |
| `released` | Confirmado: el album ya está disponible |
| `postponed` | No salió a las 03:00 del día del release (postergado o cancelado) |

---

## Backend

### Repo (`services/upcoming_releases_repo.py`)

Todas las queries filtran por `status = 'pending'`. Funciones principales:

| Función | Descripción |
|---|---|
| `list_upcoming_releases` | Releases pending futuros (desde hoy) |
| `list_upcoming_releases_cached` | Versión cacheada con smart TTL |
| `list_upcoming_30d` | Releases pending de hoy + 30 días (rolling window) |
| `list_upcoming_30d_cached` | Versión cacheada con smart TTL |
| `get_upcoming_by_artist_id` | Próximo release pending de un artista |
| `get_upcoming_by_artist_id_cached` | Versión cacheada (7 días si no hay upcoming) |
| `mark_as_released` | Marca `status=released` + `confirmed_at` |
| `mark_as_postponed` | Marca `status=postponed` + `confirmed_at` |
| `get_todays_pending` | Releases de hoy que siguen pending (para el cron) |

### Smart TTL

El caché expira dinámicamente según la proximidad del siguiente release:

| Distancia | TTL |
|---|---|
| Ya pasó | 1 hora |
| Hoy | 2 horas |
| Mañana | 12 horas |
| N días | N días + 2 horas |
| Sin fecha | 7 días |

### Endpoints (`routes/upcoming_releases.py`)

| Endpoint | Descripción |
|---|---|
| `GET /upcoming-releases` | Todos los releases pending futuros |
| `GET /upcoming-releases/next` | Rolling 30 días desde hoy |

Ambos aplican `_filter_complete`: excluye releases sin `thumbnail` o sin `artist_id`.

Ambos devuelven:

```json
{
  "ok": true,
  "count": 5,
  "releases": [
    {
      "id": "uuid",
      "release_date": "2026-04-04",
      "artist": "Charli xcx",
      "album": "BRAT 2",
      "label": "Atlantic",
      "thumbnail": "https://...",
      "track_count": 12,
      "artist_id": "UC..."
    }
  ]
}
```

### Check en tiempo real (`services/artist_service.py`)

Función `_check_upcoming_released` se ejecuta dentro de `get_artist()`:

1. ¿El artista tiene un upcoming pending? (cacheado, 7 días si no hay)
2. ¿El nombre del upcoming matchea con el último album del artista?
3. Si sí → `mark_as_released` + invalidar cachés de `UPCOMING_RELEASES` y `UPCOMING_ARTIST`

**Cero calls extra**: usa data que `get_artist()` ya trae.

### Caché

| CacheType | Schedule | TTL default |
|---|---|---|
| `UPCOMING_RELEASES` | MANUAL | 86400 (smart TTL overridea) |
| `UPCOMING_ARTIST` | MANUAL | 86400 (smart TTL overridea) |

Invalidación: `set_manual_version` cuando se confirma un release (tiempo real o cron).

---

## Cron (`scripts/check_releases.py`)

Script independiente de FastAPI. No bloquea el servidor, no corre en el mismo proceso.

### Modo normal (22:00)

```bash
python scripts/check_releases.py
```

1. `get_todays_pending()` → si vacío, sale
2. Por cada release: chequea si el album ya está entre los albums del artista
3. Si está → `mark_as_released`
4. Delay de 3 segundos entre cada call
5. Si hubo releases confirmados → invalida cachés

### Modo fallback (03:00)

```bash
python scripts/check_releases.py --fallback
```

1. `get_todays_pending()` → si vacío, sale
2. Los que quedan → `mark_as_postponed`
3. Invalida cachés
4. Cero calls externos

### Crontab

```
0 22 * * * cd /ruta/al/proyecto && /usr/bin/python3 scripts/check_releases.py >> /var/log/check_releases.log 2>&1
0 3  * * * cd /ruta/al/proyecto && /usr/bin/python3 scripts/check_releases.py --fallback >> /var/log/check_releases.log 2>&1
```

---

## Frontend

### Tipo (`services/musicService.ts`)

```typescript
export type UpcomingRelease = {
  id: string;
  release_date: string | null;
  artist: string | null;
  album: string | null;
  label: string | null;
  thumbnail: string | null;
  track_count: number | null;
  artist_id: string | null;
};
```

### Método en `musicService`

`getUpcomingReleases` → `GET /upcoming-releases/next` con `cacheWrap` y version `upcoming-releases`.

### Hook en `useMusicApi`

`getUpcomingReleases` → `useCallback` con `versions` como dependencia.

### Fetch en `useHomeFeed`

`refreshUpcomingReleases` → llama a `musicService.getUpcomingReleases(versions)` y setea `upcomingReleases`.

### Render en `HomeScreen`

```
<FeedSection
  title="Próximos lanzamientos"
  items={upcomingReleases.map(...)}
  type="album"
  feedKey="upcoming-releases"
/>
```

Con `feedKey` tiene el `>` para ver más, que navega a `FeedListScreen` con `key="upcoming-releases"`.

### FeedListScreen

Branch `upcoming-releases` que llama a `getUpcomingReleases()` y mapea los items.

---

## Flujo completo: ciclo de vida de un release

```
1. Se inserta en la DB con status=pending (via seed_upcoming_releases.py)
2. Aparece en "Próximos lanzamientos" en el Home (rolling 30 días)
3. Aparece en la pantalla del artista como upcoming
4. El día del release:
   a. Si alguien visita al artista → check en tiempo real lo marca released
   b. Si nadie lo visita → cron 22:00 lo chequea
   c. Si a las 03:00 sigue pending → cron lo marca postponed
5. Una vez released/postponed → desaparece de todas las queries automáticamente
```

---

## Referencias

> SEE: [Supabase — Database](https://supabase.com/docs/guides/database)
> SEE: [FastAPI — Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/)
> SEE: [FastAPI — Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
> SEE: [Crontab Guru](https://crontab.guru/)
> SEE: [React Native — State Management](https://reactnative.dev/docs/intro-react)
> DOC: [Expo Router — Navigation](https://docs.expo.dev/router/introduction/)
> DOC: [AsyncStorage](https://react-native-async-storage.github.io/async-storage/)