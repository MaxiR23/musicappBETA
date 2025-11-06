# Sistema de Estadísticas de Actividad Musical

## Descripción General

Sistema completo de tracking, agregación y análisis de actividad de usuarios en una aplicación de música. Implementa un modelo de tres capas que permite generar reportes mensuales estilo "Spotify Wrapped" o "Apple Music Replay", manteniendo la base de datos optimizada mediante purgas automáticas.

## Arquitectura del Sistema

### Capa 1: Datos RAW
- **Tabla**: `user_activity`
- **Propósito**: Almacena cada reproducción individual con contador de plays
- **Retención**: 60 días
- **Actualización**: Tiempo real (UPSERT al reproducir)

### Capa 2: Estadísticas Semanales
- **Tabla**: `user_weekly_stats`
- **Propósito**: Top 5-10 items por tipo (artist/album/track) de cada semana
- **Retención**: 90 días
- **Actualización**: Cada domingo a las 23:59 (agregación automática)

### Capa 3: Estadísticas Mensuales
- **Tabla**: `user_monthly_stats`
- **Propósito**: Top 5-10 items por tipo del mes completo
- **Retención**: Permanente (base para Replay anual)
- **Actualización**: Día 1 de cada mes a las 3:00 AM (agregación automática)

## Esquema de Base de Datos

### Tabla: user_activity

```sql
CREATE TABLE public.user_activity (
  id UUID NOT NULL DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  event_type public.app_event_type NOT NULL,
  entity_type public.app_entity_type NOT NULL,
  entity_id TEXT NULL,
  context_type public.app_entity_type NULL,
  context_id TEXT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  play_count INTEGER NOT NULL DEFAULT 1,
  
  CONSTRAINT user_activity_pkey PRIMARY KEY (id),
  CONSTRAINT user_activity_user_id_fkey FOREIGN KEY (user_id) 
    REFERENCES auth.users (id) ON DELETE CASCADE
);

CREATE INDEX ua_user_time_idx ON public.user_activity 
  USING btree (user_id, occurred_at DESC);
  
CREATE INDEX ua_user_entity_idx ON public.user_activity 
  USING btree (user_id, entity_type, occurred_at DESC);
  
CREATE INDEX ua_user_event_idx ON public.user_activity 
  USING btree (user_id, event_type, occurred_at DESC);
```

**Campos clave:**
- `play_count`: Contador de reproducciones (se incrementa con UPSERT)
- `metadata`: Almacena `display_name` y `thumbnail_url` para caché

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

**Estructura de JSONB stats:**
```json
[
  {
    "entity_id": "BACnvj5jAh0",
    "play_count": 45,
    "display_name": "It Makes You Forget",
    "thumbnail_url": "https://..."
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

## Sistema de Logging

### Backend: Lógica de UPSERT

**Archivo**: `services/activity_service.py`

**Comportamiento:**
1. Primera reproducción: INSERT con `play_count = 1`
2. Reproducciones subsiguientes: UPDATE incrementando `play_count` y actualizando `occurred_at`
3. Se aplica a: artistas, álbumes y canciones

**Funciones clave:**
- `_upsert_album_artist_play()`: Maneja UPSERT para álbumes y artistas
- `log_activity()`: Router principal que decide qué tipo de UPSERT usar

### Frontend: Tracking de 30 Segundos

**Archivo**: `providers/MusicProvider.tsx`

**Estrategia:**
- Solo loggea canciones después de 30 segundos de reproducción REAL
- Usa el evento `PlaybackProgressUpdated` de TrackPlayer
- Maneja pausas correctamente (no cuenta tiempo pausado)
- Elimina logging de clicks accidentales

**Implementación:**
```typescript
const subProgress = TrackPlayer.addEventListener(
  Event.PlaybackProgressUpdated, 
  async (progress) => {
    const currentPosition = progress.position;
    
    if (currentPosition >= 30) {
      // Loggear track
      logPlayTrack(trackId, trackMeta);
    }
  }
);
```

## Scripts de Agregación

### Script Semanal

**Archivo**: `scripts/aggregate_weekly_stats.py`

**Ejecución**: Cada domingo a las 23:59

**Proceso:**
1. Calcula el lunes de la semana pasada
2. Obtiene todos los usuarios con actividad en esa semana
3. Para cada usuario:
   - Lee `user_activity` de la semana
   - Agrupa por `entity_type` y `entity_id`
   - Suma `play_count` de cada entidad
   - Ordena por `play_count` descendente
   - Guarda top 5-10 en `user_weekly_stats`
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
2. Obtiene todos los usuarios con actividad en ese mes
3. Para cada usuario:
   - Lee `user_activity` del mes completo
   - Agrupa por `entity_type` y `entity_id`
   - Suma `play_count` de cada entidad
   - Ordena por `play_count` descendente
   - Guarda top 5-10 en `user_monthly_stats`
4. Crea 3 registros por usuario (artist, album, track)

**Comando manual:**
```bash
python scripts/aggregate_monthly_stats.py
```

**Nota**: Lee directamente de `user_activity` para máxima precisión. Optimización futura: consolidar desde `user_weekly_stats`.

### Script de Purga

**Archivo**: `scripts/purge_old_data.py`

**Ejecución**: Cada domingo a las 4:00 AM

**Proceso:**
1. Borra registros de `user_activity` más antiguos que 60 días
2. Borra registros de `user_weekly_stats` más antiguos que 90 días
3. Nunca borra `user_monthly_stats` (permanente)

**Comando manual:**
```bash
python scripts/purge_old_data.py
```

## GitHub Actions Workflows

### Workflow: Agregación Semanal

**Archivo**: `.github/workflows/aggregate-weekly-stats.yml`

**Schedule**: `59 2 * * 1` (Lunes 2:59 UTC = Domingo 23:59 Argentina)

**Variables de entorno requeridas:**
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`

### Workflow: Agregación Mensual

**Archivo**: `.github/workflows/aggregate-monthly-stats.yml`

**Schedule**: `0 6 1 * *` (Día 1 de cada mes, 6:00 UTC = 3:00 AM Argentina)

**Variables de entorno requeridas:**
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`

### Workflow: Purga Automática

**Archivo**: `.github/workflows/purge-old-data.yml`

**Schedule**: `0 7 * * 1` (Lunes 7:00 UTC = Domingo 4:00 AM Argentina)

**Variables de entorno requeridas:**
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`

**Nota**: Todos los workflows incluyen `workflow_dispatch` para ejecución manual desde GitHub Actions.

## Flujo de Datos Completo

### Tiempo Real (Usuario reproduciendo)
```
Usuario reproduce canción
    ↓
Frontend: Espera 30 segundos
    ↓
API: POST /plays/tracks/{track_id}
    ↓
Backend: UPSERT en user_activity
    ↓
Primera vez: INSERT play_count=1
    ↓
Subsiguiente: UPDATE play_count+1
```

### Agregación Semanal (Cada domingo 23:59)
```
GitHub Action se dispara
    ↓
Script lee user_activity de la semana pasada
    ↓
Agrupa y suma play_counts por entidad
    ↓
Guarda top 5-10 en user_weekly_stats
    ↓
3 registros por usuario (artist/album/track)
```

### Agregación Mensual (Día 1 a las 3:00 AM)
```
GitHub Action se dispara
    ↓
Script lee user_activity del mes pasado
    ↓
Agrupa y suma play_counts por entidad
    ↓
Guarda top 5-10 en user_monthly_stats
    ↓
3 registros por usuario (permanentes)
```

### Purga Automática (Cada domingo 4:00 AM)
```
GitHub Action se dispara
    ↓
Borra user_activity > 60 días
    ↓
Borra user_weekly_stats > 90 días
    ↓
Mantiene user_monthly_stats intacto
```

## Configuración Requerida

### Secrets de GitHub

Configurar en: `Settings > Secrets and variables > Actions`

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=eyJhbGc...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGc...
```

### Variables de Entorno Local

**Archivo**: `.env` (backend)

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=eyJhbGc...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGc...
```

### Dependencias Python

**Archivo**: `requirements.txt`

Librerías críticas:
- `supabase==2.4.0`
- `python-dotenv==1.1.0`
- `python-dateutil==2.9.0.post0`

## Casos de Uso

### Generar Replay Mensual

```python
# Endpoint: GET /api/stats/monthly/{user_id}/{month}

def get_monthly_stats(user_id: str, month: str):
    result = sb.table('user_monthly_stats') \
        .select('entity_type, stats') \
        .eq('user_id', user_id) \
        .eq('month', month) \
        .execute()
    
    return {
        'artists': result[0]['stats'] if result[0]['entity_type'] == 'artist' else [],
        'albums': result[1]['stats'] if result[1]['entity_type'] == 'album' else [],
        'tracks': result[2]['stats'] if result[2]['entity_type'] == 'track' else []
    }
```

### Obtener Top Semanal

```python
# Endpoint: GET /api/stats/weekly/{user_id}

def get_current_week_stats(user_id: str):
    today = datetime.now()
    week_start = (today - timedelta(days=today.weekday())).strftime('%Y-%m-%d')
    
    result = sb.table('user_weekly_stats') \
        .select('entity_type, stats') \
        .eq('user_id', user_id) \
        .eq('week_start', week_start) \
        .execute()
    
    return format_stats(result.data)
```

### Generar Replay Anual

```python
# Endpoint: GET /api/stats/yearly/{user_id}/{year}

def get_yearly_stats(user_id: str, year: int):
    # Lee todos los meses del año desde user_monthly_stats
    result = sb.table('user_monthly_stats') \
        .select('month, entity_type, stats') \
        .eq('user_id', user_id) \
        .gte('month', f'{year}-01-01') \
        .lte('month', f'{year}-12-31') \
        .execute()
    
    # Consolida play_counts de los 12 meses
    return consolidate_yearly(result.data)
```

## Métricas y Rendimiento

### Estimación de Volumen (1000 usuarios activos)

**user_activity** (60 días de retención):
- Promedio: 50 canciones/día/usuario
- Total: 50 × 1000 × 60 = 3,000,000 registros
- Con UPSERT: ~50,000 registros únicos (reducción 98%)

**user_weekly_stats** (90 días de retención):
- 3 registros/usuario/semana × 13 semanas = 39,000 registros

**user_monthly_stats** (permanente):
- 3 registros/usuario/mes × 12 meses/año = 36,000 registros/año

**Total estimado**: ~125,000 registros activos

### Optimizaciones Implementadas

1. **UPSERT en lugar de INSERT**: Reduce 98% el volumen de datos
2. **Logging después de 30 segundos**: Elimina clicks accidentales
3. **Índices compuestos**: Queries < 50ms en promedio
4. **JSONB para arrays**: Flexibilidad sin tablas relacionales complejas
5. **Purga automática**: Mantiene DB limpia sin intervención manual

## Troubleshooting

### Los scripts no encuentran datos

**Problema**: Scripts buscan semana/mes PASADO, pero los datos son actuales.

**Solución temporal para testing**:
```python
# En aggregate_weekly_stats.py
today = datetime.now()
week_start = (today - timedelta(days=today.weekday())).strftime('%Y-%m-%d')

# En aggregate_monthly_stats.py
month = datetime.now().replace(day=1).strftime('%Y-%m-%d')
```

### GitHub Actions no se ejecutan

**Verificar**:
1. Workflows están en `.github/workflows/`
2. Secrets están configurados en GitHub
3. Revisar logs en Actions tab
4. Probar ejecución manual con `workflow_dispatch`

### Purga borra demasiado/poco

**Ajustar retención**:
```python
# En purge_old_data.py
purge_user_activity(days=60)  # Cambiar número de días
purge_weekly_stats(days=90)
```

## Roadmap Futuro

### Optimizaciones Pendientes
- Consolidar stats mensuales desde `user_weekly_stats` en lugar de `user_activity`
- Implementar caché de queries frecuentes (Redis)
- Agregar webhook de notificación al completar agregaciones

### Features Adicionales
- Comparación usuario vs comunidad (percentiles)
- Playlist automática "On Repeat" basada en play_count

## Licencia y Créditos

Sistema inspirado en:
- Spotify Wrapped
- Apple Music Replay

Tecnologías utilizadas:
- PostgreSQL (Supabase)
- Python 3.11
- GitHub Actions
- React Native (frontend)
