# Sistema de Estadísticas de Actividad Musical

## Descripción General

Sistema completo de tracking, agregación y análisis de actividad de usuarios en una aplicación de música. Implementa un modelo de tres capas que permite generar reportes mensuales estilo "Spotify Wrapped" o "Apple Music Replay", manteniendo la base de datos optimizada mediante purgas automáticas.

## Arquitectura del Sistema

### Capa 1: Datos RAW
- **Tabla**: `play_events`
- **Propósito**: Almacena cada reproducción individual (1 fila = 1 play)
- **Retención**: 60 días
- **Actualización**: Tiempo real (INSERT al reproducir)

### Capa 2: Estadísticas Semanales
- **Tabla**: `user_weekly_stats`
- **Propósito**: Top 10 items por tipo (artist/album/track) de cada semana
- **Retención**: 90 días
- **Actualización**: Cada domingo a las 23:59 (agregación desde `play_events`)

### Capa 3: Estadísticas Mensuales
- **Tabla**: `user_monthly_stats`
- **Propósito**: Top 10 items por tipo del mes completo
- **Retención**: Permanente (base para Replay anual)
- **Actualización**: Día 1 de cada mes a las 3:00 AM (consolidación desde `user_weekly_stats`)

## Esquema de Base de Datos

### Tabla: play_events

```sql
CREATE TABLE public.play_events (
  id UUID NOT NULL DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  track_id TEXT NOT NULL,
  played_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  
  CONSTRAINT play_events_pkey PRIMARY KEY (id),
  CONSTRAINT play_events_user_id_fkey FOREIGN KEY (user_id) 
    REFERENCES auth.users (id) ON DELETE CASCADE
);

CREATE INDEX pe_user_time_idx ON public.play_events 
  USING btree (user_id, played_at DESC);
  
CREATE INDEX pe_user_track_idx ON public.play_events 
  USING btree (user_id, track_id);
```

**Estructura de metadata:**
```json
{
  "track_name": "Viuda Negra",
  "artist_id": "UCxwa4Iq-qOHIifC6FOpvL2w",
  "artist_name": "WOS",
  "album_id": "MPREb_g3PVGetl3BE",
  "album_name": "SAETA",
  "thumbnail_url": "https://lh3.googleusercontent.com/..."
}
```

### Tabla: recent_activity

```sql
CREATE TABLE public.recent_activity (
  id UUID NOT NULL DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  entity_type public.app_entity_type NOT NULL,
  entity_id TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  
  CONSTRAINT recent_activity_pkey PRIMARY KEY (id),
  CONSTRAINT recent_activity_unique UNIQUE (user_id, entity_type, entity_id),
  CONSTRAINT recent_activity_user_id_fkey FOREIGN KEY (user_id) 
    REFERENCES auth.users (id) ON DELETE CASCADE
);

CREATE INDEX ra_user_type_idx ON public.recent_activity 
  USING btree (user_id, entity_type, updated_at DESC);
```

**Propósito**: Tracking de items recientes para UI (últimos álbumes/artistas escuchados).

### Tabla: user_weekly_stats

```sql
CREATE TABLE public.user_weekly_stats (
  id UUID NOT NULL DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  week_start DATE NOT NULL,
  entity_type public.app_entity_type NOT NULL,
  stats JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  
  CONSTRAINT user_weekly_stats_pkey PRIMARY KEY (id),
  CONSTRAINT user_weekly_stats_user_id_fkey FOREIGN KEY (user_id) 
    REFERENCES auth.users (id) ON DELETE CASCADE,
  CONSTRAINT user_weekly_stats_unique UNIQUE (user_id, week_start, entity_type)
);

CREATE INDEX uws_user_week_idx ON public.user_weekly_stats 
  USING btree (user_id, week_start DESC);
  
CREATE INDEX uws_user_type_idx ON public.user_weekly_stats 
  USING btree (user_id, entity_type, week_start DESC);
```

**Estructura de JSONB stats por entity_type:**

**track:**
```json
[
  {
    "entity_id": "h984FVmists",
    "display_name": "Viuda Negra",
    "thumbnail_url": "https://...",
    "play_count": 5,
    "artist_id": "UCxwa4Iq...",
    "artist_name": "WOS",
    "album_id": "MPREb_g3PVGetl3BE",
    "album_name": "SAETA"
  }
]
```

**album:**
```json
[
  {
    "entity_id": "MPREb_g3PVGetl3BE",
    "display_name": "SAETA",
    "thumbnail_url": "https://...",
    "play_count": 8,
    "artist_id": "UCxwa4Iq...",
    "artist_name": "WOS"
  }
]
```

**artist:**
```json
[
  {
    "entity_id": "UCxwa4Iq...",
    "display_name": "WOS",
    "thumbnail_url": "https://...",
    "play_count": 15
  }
]
```

### Tabla: user_monthly_stats

```sql
CREATE TABLE public.user_monthly_stats (
  id UUID NOT NULL DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  month DATE NOT NULL,
  entity_type public.app_entity_type NOT NULL,
  stats JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  
  CONSTRAINT user_monthly_stats_pkey PRIMARY KEY (id),
  CONSTRAINT user_monthly_stats_user_id_fkey FOREIGN KEY (user_id) 
    REFERENCES auth.users (id) ON DELETE CASCADE,
  CONSTRAINT user_monthly_stats_unique UNIQUE (user_id, month, entity_type)
);

CREATE INDEX ums_user_month_idx ON public.user_monthly_stats 
  USING btree (user_id, month DESC);
  
CREATE INDEX ums_user_type_idx ON public.user_monthly_stats 
  USING btree (user_id, entity_type, month DESC);
```

**Estructura de stats**: Igual que `user_weekly_stats`.

## RPCs de Agregación

### aggregate_user_weekly_stats

Agrega estadísticas semanales para un usuario. Hace GROUP BY en Postgres y retorna solo top 10 por tipo.

**Uso desde Python:**
```python
sb.rpc('aggregate_user_weekly_stats', {
    'p_user_id': user_id,
    'p_week_start': '2026-02-17',
    'p_week_end': '2026-02-24'
}).execute()
```

**Retorna:**
```json
{
  "track": [...top 10...],
  "artist": [...top 10...],
  "album": [...top 10...]
}
```

**SQL:**
```sql
CREATE OR REPLACE FUNCTION aggregate_user_weekly_stats(
  p_user_id uuid,
  p_week_start date,
  p_week_end date
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_tracks jsonb;
  v_artists jsonb;
  v_albums jsonb;
BEGIN
  -- Top 10 tracks (artist_name completo con feats)
  SELECT COALESCE(jsonb_agg(t ORDER BY t.play_count DESC), '[]'::jsonb)
  INTO v_tracks
  FROM (
    SELECT 
      track_id as entity_id,
      (array_agg(metadata->>'track_name') FILTER (WHERE metadata->>'track_name' IS NOT NULL))[1] as display_name,
      (array_agg(metadata->>'thumbnail_url') FILTER (WHERE metadata->>'thumbnail_url' IS NOT NULL))[1] as thumbnail_url,
      (array_agg(metadata->>'artist_id') FILTER (WHERE metadata->>'artist_id' IS NOT NULL))[1] as artist_id,
      (array_agg(metadata->>'artist_name') FILTER (WHERE metadata->>'artist_name' IS NOT NULL))[1] as artist_name,
      (array_agg(metadata->>'album_id') FILTER (WHERE metadata->>'album_id' IS NOT NULL))[1] as album_id,
      (array_agg(metadata->>'album_name') FILTER (WHERE metadata->>'album_name' IS NOT NULL))[1] as album_name,
      COUNT(*)::int as play_count
    FROM play_events
    WHERE user_id = p_user_id 
      AND played_at >= p_week_start 
      AND played_at < p_week_end
    GROUP BY track_id
    ORDER BY play_count DESC
    LIMIT 10
  ) t;

  -- Top 10 artists (primer nombre, sin feats)
  SELECT COALESCE(jsonb_agg(a ORDER BY a.play_count DESC), '[]'::jsonb)
  INTO v_artists
  FROM (
    SELECT 
      metadata->>'artist_id' as entity_id,
      SPLIT_PART((array_agg(metadata->>'artist_name') FILTER (WHERE metadata->>'artist_name' IS NOT NULL))[1], ', ', 1) as display_name,
      (array_agg(metadata->>'thumbnail_url') FILTER (WHERE metadata->>'thumbnail_url' IS NOT NULL))[1] as thumbnail_url,
      COUNT(*)::int as play_count
    FROM play_events
    WHERE user_id = p_user_id 
      AND played_at >= p_week_start 
      AND played_at < p_week_end
      AND metadata->>'artist_id' IS NOT NULL
    GROUP BY metadata->>'artist_id'
    ORDER BY play_count DESC
    LIMIT 10
  ) a;

  -- Top 10 albums (primer nombre, sin feats)
  SELECT COALESCE(jsonb_agg(al ORDER BY al.play_count DESC), '[]'::jsonb)
  INTO v_albums
  FROM (
    SELECT 
      metadata->>'album_id' as entity_id,
      (array_agg(metadata->>'album_name') FILTER (WHERE metadata->>'album_name' IS NOT NULL))[1] as display_name,
      (array_agg(metadata->>'thumbnail_url') FILTER (WHERE metadata->>'thumbnail_url' IS NOT NULL))[1] as thumbnail_url,
      (array_agg(metadata->>'artist_id') FILTER (WHERE metadata->>'artist_id' IS NOT NULL))[1] as artist_id,
      SPLIT_PART((array_agg(metadata->>'artist_name') FILTER (WHERE metadata->>'artist_name' IS NOT NULL))[1], ', ', 1) as artist_name,
      COUNT(*)::int as play_count
    FROM play_events
    WHERE user_id = p_user_id 
      AND played_at >= p_week_start 
      AND played_at < p_week_end
      AND metadata->>'album_id' IS NOT NULL
    GROUP BY metadata->>'album_id'
    ORDER BY play_count DESC
    LIMIT 10
  ) al;

  RETURN jsonb_build_object(
    'track', v_tracks,
    'artist', v_artists,
    'album', v_albums
  );
END;
$$;
```

**Notas:**
- `FILTER (WHERE ... IS NOT NULL)` evita que un registro con null arruine el resultado
- `SPLIT_PART(..., ', ', 1)` extrae solo el primer artista (dueño del álbum, sin feats)
- Tracks mantienen el `artist_name` completo con feats
- Albums y Artists usan solo el primer nombre

## Sistema de Logging

### Backend: Lógica de INSERT

**Archivo**: `services/activity_service.py`

**Comportamiento:**
1. Cada reproducción = 1 INSERT en `play_events`
2. El metadata incluye toda la info del track (artist, album, etc.)
3. Se actualiza `recent_activity` para UI de recientes

**Funciones clave:**
- `log_play()`: Inserta en `play_events` y actualiza `recent_activity`

### Frontend: Tracking de 30 Segundos

**Archivo**: `providers/MusicProvider.tsx`

**Estrategia:**
- Solo loggea canciones después de 30 segundos de reproducción REAL
- Usa el evento `PlaybackProgressUpdated` de TrackPlayer
- Maneja pausas correctamente (no cuenta tiempo pausado)
- Elimina logging de clicks accidentales

## Scripts de Agregación

### Script Semanal

**Archivo**: `scripts/aggregate_weekly_stats.py`

**Ejecución**: Cada domingo a las 23:59

**Proceso:**
1. Calcula el lunes de la semana pasada
2. Lee `play_events` de esa semana
3. Para cada usuario:
   - Agrupa plays por track_id, artist_id, album_id
   - Extrae metadata de cada play
   - Cuenta plays por entidad
   - Guarda top 10 en `user_weekly_stats`
4. Crea 3 registros por usuario (artist, album, track)

**Comando manual:**
```bash
python scripts/aggregate_weekly_stats.py
```

### Script Mensual

**Archivo**: `scripts/aggregate_monthly_stats.py`

**Ejecución**: Día 1 de cada mes a las 3:00 AM

**Proceso:**
1. Calcula el primer día del mes pasado
2. Identifica las semanas (lunes) que caen en ese mes
3. Lee `user_weekly_stats` de esas semanas
4. Para cada usuario:
   - Consolida stats de las 4-5 semanas
   - Suma play_counts por entidad
   - Guarda top 10 en `user_monthly_stats`
5. Crea 3 registros por usuario (permanentes)

**Comando manual:**
```bash
python scripts/aggregate_monthly_stats.py
```

### Script de Purga

**Archivo**: `scripts/purge_old_data.py`

**Ejecución**: Cada semana

**Proceso:**
1. Borra registros de `play_events` más antiguos que 60 días
2. Borra registros de `user_weekly_stats` más antiguos que 90 días
3. Nunca borra `user_monthly_stats` (permanente)

**Comando manual:**
```bash
python scripts/purge_old_data.py
```

## Flujo de Datos Completo

### Tiempo Real (Usuario reproduciendo)
```
Usuario reproduce canción
    ↓
Frontend: Espera 30 segundos
    ↓
API: POST /plays/tracks/{track_id}
    ↓
Backend: INSERT en play_events
    ↓
Backend: UPSERT en recent_activity
```

### Agregación Semanal (Cada domingo 23:59)
```
GitHub Action se dispara
    ↓
Script lee play_events de la semana pasada
    ↓
Agrupa y cuenta plays por entidad
    ↓
Extrae metadata (artist_id, album_id, etc.)
    ↓
Guarda top 10 en user_weekly_stats
    ↓
3 registros por usuario (artist/album/track)
```

### Agregación Mensual (Día 1 a las 3:00 AM)
```
GitHub Action se dispara
    ↓
Script lee user_weekly_stats de las semanas del mes
    ↓
Consolida play_counts de 4-5 semanas
    ↓
Guarda top 10 en user_monthly_stats
    ↓
3 registros por usuario (permanentes)
```

### Purga Automática (Cada semana)
```
GitHub Action se dispara
    ↓
Borra play_events > 60 días
    ↓
Borra user_weekly_stats > 90 días
    ↓
Mantiene user_monthly_stats intacto
```

## Sistema de Recomendaciones

### Seeds desde Actividad

**Archivo**: `services/activity_repo.py`

**Función**: `recent_seeds_from_activity()`

**Comportamiento:**
1. Lee `user_weekly_stats` de la semana más reciente
2. Retorna top N artists y albums como seeds
3. Incluye metadata completa para cada seed

**Uso**: El script `store_user_recommendations.py` usa estos seeds para generar recomendaciones personalizadas cada lunes.

## Métricas y Rendimiento

### Estimación de Volumen (1000 usuarios activos)

**play_events** (60 días de retención):
- Promedio: 50 canciones/día/usuario
- Total: 50 × 1000 × 60 = 3,000,000 registros

**user_weekly_stats** (90 días de retención):
- 3 registros/usuario/semana × 13 semanas = 39,000 registros

**user_monthly_stats** (permanente):
- 3 registros/usuario/mes × 12 meses/año = 36,000 registros/año

### Optimizaciones Implementadas

1. **Metadata en play_events**: Un INSERT registra toda la info necesaria
2. **Logging después de 30 segundos**: Elimina clicks accidentales
3. **Índices compuestos**: Queries < 50ms en promedio
4. **Consolidación semanal→mensual**: Mensual lee ~4 filas en vez de miles
5. **Purga automática**: Mantiene DB limpia sin intervención manual
6. **Seeds desde weekly_stats**: Recomendaciones leen 2 filas, no 400

## Casos de Uso

### Generar Replay Mensual

```python
def get_monthly_stats(user_id: str, month: str):
    result = sb.table('user_monthly_stats') \
        .select('entity_type, stats') \
        .eq('user_id', user_id) \
        .eq('month', month) \
        .execute()
    
    stats = {row['entity_type']: row['stats'] for row in result.data}
    return {
        'artists': stats.get('artist', []),
        'albums': stats.get('album', []),
        'tracks': stats.get('track', [])
    }
```

### Obtener Top Semanal

```python
def get_weekly_stats(user_id: str, week_start: str):
    result = sb.table('user_weekly_stats') \
        .select('entity_type, stats') \
        .eq('user_id', user_id) \
        .eq('week_start', week_start) \
        .execute()
    
    stats = {row['entity_type']: row['stats'] for row in result.data}
    return stats
```

### Generar Replay Anual

```python
def get_yearly_stats(user_id: str, year: int):
    result = sb.table('user_monthly_stats') \
        .select('month, entity_type, stats') \
        .eq('user_id', user_id) \
        .gte('month', f'{year}-01-01') \
        .lte('month', f'{year}-12-31') \
        .execute()
    
    # Consolida play_counts de los 12 meses
    return consolidate_yearly(result.data)
```

## Troubleshooting

### Los scripts no encuentran datos

**Problema**: Scripts buscan semana/mes PASADO, pero los datos son actuales.

**Solución temporal para testing**:
```python
# En aggregate_weekly_stats.py - cambiar get_monday_of_last_week()
today = datetime.now()
week_start = (today - timedelta(days=today.weekday())).strftime('%Y-%m-%d')
```

### GitHub Actions no se ejecutan

**Verificar**:
1. Workflows están en `.github/workflows/`
2. Secrets están configurados en GitHub
3. Revisar logs en Actions tab
4. Probar ejecución manual con `workflow_dispatch`

## Roadmap Futuro

### Features Adicionales
- Comparación usuario vs comunidad (percentiles)
- Playlist automática "On Repeat" basada en play_count
- Wrapped anual con visualizaciones

## Licencia y Créditos

Sistema inspirado en:
- Spotify Wrapped
- Apple Music Replay

Tecnologías utilizadas:
- PostgreSQL (Supabase)
- Python 3.11
- GitHub Actions
- React Native (frontend)