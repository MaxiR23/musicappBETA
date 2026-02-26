# Documentación: Scraper de Álbumes 2025

## Descripción General

Sistema automatizado para obtener información de álbumes que saldrán en noviembre/diciembre 2025, incluyendo:
- Metadata de álbumes desde Wikipedia
- Covers en alta resolución desde iTunes API
- Artist IDs desde YT Music API

---

## Tabla de Contenidos

1. [Requisitos](#requisitos)
2. [Scripts Disponibles](#scripts-disponibles)
3. [Rate Limits de iTunes](#rate-limits-de-itunes)
4. [Uso del Scraper](#uso-del-scraper)
5. [Seedear Base de Datos](#seedear-base-de-datos)
6. [Troubleshooting](#troubleshooting)
7. [Estructura del JSON Output](#estructura-del-json-output)
8. [Actualización Futura](#actualización-futura)
9. [Notas Importantes](#notas-importantes)
10. [Flujo Completo del Sistema](#flujo-completo-del-sistema)
11. [Archivos del Proyecto](#archivos-del-proyecto)
12. [Referencias y Recursos](#referencias-y-recursos)
13. [Seguridad y Best Practices](#seguridad-y-best-practices)
14. [Estadísticas del Último Run](#estadísticas-del-último-run)
15. [Checklist de Ejecución](#checklist-de-ejecución)
16. [Próximos Pasos](#próximos-pasos)

---

## Requisitos

### Dependencias Python

```bash
pip install requests beautifulsoup4 httpx ytmusicapi
```

### Variables de Entorno

Configurar en `.env`:

```bash
SUPABASE_URL=tu_url
SUPABASE_KEY=tu_key
```

---

## Scripts Disponibles

### 1. `scraper_wikipedia_itunes.py`

**Ubicación:** `backend/scraper_wikipedia_itunes.py`

**Función:** Scrapea Wikipedia para obtener álbumes 2025, busca covers en iTunes y artist IDs en YT Music.

**Output:** `albums_covers.json` con 104 álbumes

**Características:**
- Scraping de Wikipedia automático
- Filtrado de Nov/Dec 2025 + TBA
- Búsqueda inteligente de covers en iTunes (12 países)
- Búsqueda de artist IDs en YT Music
- Manejo de rate limits con delays configurables
- Retry logic para errores 429

**Ejecución:**

```bash
# Normal (104 álbumes, ~35 minutos)
python scraper_wikipedia_itunes.py

# Solo primeros 5 (para testear)
python scraper_wikipedia_itunes.py --limit 5
```

---

### 2. `seed_upcoming_releases.py`

**Ubicación:** `backend/scripts/seed_upcoming_releases.py`

**Función:** Inserta los álbumes del JSON en Supabase.

**Uso:**

```bash
# Preview (no inserta nada)
python scripts/seed_upcoming_releases.py albums_covers.json --dry-run

# Insertar (borra releases anteriores)
python scripts/seed_upcoming_releases.py albums_covers.json --clear
```

---

## Rate Limits de iTunes

### Límite Oficial

**20 requests por minuto por IP** (ver enlaces en Referencias y Recursos).

### Configuración Actual

```python
DELAY_BETWEEN_ALBUMS = 20.0  # segundos entre álbumes
DELAY_BETWEEN_REQUESTS = 1.5  # segundos entre requests internos
```

### Cálculo de Seguridad

**Con 20 segundos de delay:**
- 3 álbumes/minuto
- ~4-8 requests por álbum
- Total: 12-24 requests/minuto (objetivo: mantenerse cerca de 20/min)

**Tiempo total para 104 álbumes:** ~35 minutos

### Configuraciones NO Recomendadas

| Delay | Álbumes/min | Requests/min | Resultado |
|------:|------------:|-------------:|----------|
| 0.5s  | 120         | 480-960      | BAN rápido |
| 5s    | 12          | 48-96        | BAN rápido |
| 10s   | 6           | 24-48        | Riesgoso |
| 20s   | 3           | 12-24        | Seguro |
| 30s   | 2           | 8-16         | Muy seguro |
| 60s   | 1           | 4-8          | Ultra seguro |

### Duración del Ban

Si te bloquean por rate limit:
- Típico: 1-2 horas
- Máximo: 6-12 horas (si saturaste mucho)
- Síntomas: 403 Forbidden en todos los requests

### Soluciones al Ban

1. Esperar 2 horas
2. Cambiar IP:
   - Reiniciar router (apagar 5 min)
   - Usar VPN
3. Ejecutar en Google Colab (IP diferente)

---

## Uso del Scraper

### Ejecución Normal

```bash
python scraper_wikipedia_itunes.py
```

**Output esperado (ejemplo):**

```
======================================================================
SCRAPER DE ÁLBUMES 2025 CON COVERS
Delay: 20.0s entre álbumes
======================================================================

Scrapeando Wikipedia...
Encontrados 1416 álbumes en Wikipedia

Filtrados Nov/Dec 2025 + TBA: 104 álbumes

Tiempo estimado: ~34.7 minutos

Buscando covers y artist IDs...
(con delays de seguridad para evitar rate limits)

[1/104] Juana Molina - Doga OK OK
[2/104] Agnostic Front - Echoes in Eternity OK OK
[3/104] Allie X - Happiness Is Going to Get You NO OK
...
[104/104] Triptykon - TBA NO OK

======================================================================
RESULTADOS:
======================================================================
Total álbumes:          104
Covers encontrados:     85
Artist IDs encontrados: 95
Sin cover:              19
Sin artist ID:          9
======================================================================

Guardado en 'albums_covers.json'
```

### Interpretación de símbolos

- `OK OK` = Cover encontrado + Artist ID encontrado
- `OK NO` = Cover encontrado + Sin Artist ID
- `NO OK` = Sin cover + Artist ID encontrado
- `NO NO` = Sin cover + Sin Artist ID

### Opciones de Línea de Comandos

```bash
# Procesar solo los primeros N álbumes
python scraper_wikipedia_itunes.py --limit 5
```

### Modo Test (en el código)

Para probar con 1 solo álbum, descomentar en `main()`:

```python
albums = albums[:1]
print("TEST MODE: Procesando solo 1 álbum
")
```

---

## Seedear Base de Datos

### Paso 1: Preview (Dry Run)

```bash
python scripts/seed_upcoming_releases.py albums_covers.json --dry-run
```

### Paso 2: Insertar en Supabase

```bash
python scripts/seed_upcoming_releases.py albums_covers.json --clear
```

### Flags Disponibles

| Flag | Descripción |
|------|-------------|
| `--dry-run` | Preview sin insertar (recomendado primero) |
| `--clear` | Borra releases existentes antes de insertar |
| Sin flags | Inserta sin borrar (puede causar duplicados) |

---

## Troubleshooting

### Error: `403 Forbidden` en iTunes

**Síntomas:**
```
[DEBUG] text search failed ar 403
[DEBUG] text search failed mx 403
[DEBUG] text search failed us 403
```

**Causa:** Rate limit excedido

**Solución:**
1. Esperar 1-2 horas
2. Cambiar IP (router o VPN)
3. Ejecutar en Google Colab

**Prevención:**
- No bajar `DELAY_BETWEEN_ALBUMS` por debajo de 20s
- Si te bloquearon, subir a 30s en el próximo run

---

### Error: `ModuleNotFoundError: No module named 'ytmusicapi'`

**Solución:**
```bash
pip install ytmusicapi
```

O instalar todo:
```bash
pip install requests beautifulsoup4 httpx ytmusicapi
```

---

### Error: Algunos álbumes sin cover

**Causa:** Álbumes futuros que todavía no están publicados en iTunes

**Solución:**
- Normal y esperado: se guardan igual con `thumbnail_url: null`
- Re-scrapear más cerca de la fecha de lanzamiento

---

### Error: `artist not found at all`

**Causas posibles:**
1. Artista no existe en iTunes (muy indie/nuevo)
2. Nombre mal escrito en Wikipedia
3. Artista solo en plataformas alternativas

**Solución:**
- El script continúa y guarda lo que tenga (no es error crítico)

---

### Script muy lento

**Causa:** Delays de seguridad (intencional)

**Info:**
- Con 20s, 104 álbumes toman ~35 minutos
- No reducir el delay si no querés arriesgar un bloqueo

---

### Error: `SUPABASE_URL` not found

**Solución:** Crear/actualizar `.env`:

```bash
SUPABASE_URL=https://tu-proyecto.supabase.co
SUPABASE_KEY=tu_anon_key_aqui
```

---

### Error: `Connection timeout`

**Causas:**
1. Internet inestable
2. iTunes/Wikipedia caídos
3. Firewall bloqueando

**Solución:**
1. Reintentar más tarde
2. Verificar conectividad
3. Revisar firewall

---

## Estructura del JSON Output

### Ejemplo

```json
[
  {
    "release_date": "2025-11-05",
    "artist": "Juana Molina",
    "album": "Doga",
    "label": "Sonamos Records",
    "thumbnail": "https://is1-ssl.mzstatic.com/image/thumb/Music221/.../1200x1200bb.jpg",
    "track_count": 10,
    "artist_id": "UCmwrZKN_TKoEcCQiC2UwEVQ"
  },
  {
    "release_date": "2025-11-07",
    "artist": "Allie X",
    "album": "Happiness Is Going to Get You",
    "artist_id": "UCAillCahnZd961jaWwpt4Xw"
  },
  {
    "release_date": "TBA",
    "artist": "Playboi Carti",
    "album": "Baby Boi",
    "artist_id": "UCRB-a6u9flpg0xuBqCf9QlQ"
  }
]
```

### Campos requeridos
- `release_date` (string: "YYYY-MM-DD" o "TBA")
- `artist` (string)
- `album` (string)

### Campos opcionales
- `label` (string)
- `genre` (string)
- `thumbnail` (string URL)
- `track_count` (number)
- `artist_id` (string - YT Music browseId)

### Mapeo a Base de Datos

| JSON | Supabase Column | Tipo |
|------|------------------|------|
| `artist` | `artist_name` | text |
| `album` | `album_name` | text |
| `release_date` | `release_date` | date (null si TBA) |
| `release_date == "TBA"` | `is_tba` | boolean |
| `label` | `label` | text |
| `thumbnail` | `thumbnail_url` | text |
| `track_count` | `track_count` | integer |
| `artist_id` | `artist_id` | text |

---

## Actualización Futura

### Mediados de Diciembre 2025

Actualizar el filtro para incluir primeros 6 meses de 2026.

Buscar en `scraper_wikipedia_itunes.py` y reemplazar por:

```python
def filter_upcoming_releases(albums):
    """
    Filters upcoming releases (Nov/Dec 2025 + First half 2026)
    """
    filtered = []
    for album in albums:
        release_date = album.get("release_date", "")

        if release_date == "TBA":
            filtered.append(album)
            continue

        valid_months = [
            "2025-11", "2025-12",
            "2026-01", "2026-02", "2026-03",
            "2026-04", "2026-05", "2026-06",
        ]

        if any(release_date.startswith(month) for month in valid_months):
            filtered.append(album)

    return filtered
```

---

## Notas Importantes

### Covers faltantes (~15-20%)
- Es normal en releases futuros
- Guardar con `thumbnail_url: null` y usar placeholder en la app
- Re-scrapear más cerca de la fecha para completar

### Artist IDs faltantes (~5-10%)
- Artista no está en YT Music o nombre mal formateado
- Guardar con `artist_id: null`

### Álbumes TBA
- Se marcan con `is_tba: true`
- Útil para “próximamente” sin fecha exacta

### Performance
Optimizaciones:
- Batch insert en Supabase (1 request para 104 álbumes)
- Cache interno de búsquedas
- Búsqueda multi-país
- Fallback a búsqueda de texto
- Manejo de rate limits (429)

---

## Flujo Completo del Sistema

```
1) Wikipedia Scraping
   - Scrapea lista 2025
   - Parsea tablas HTML
   - Extrae: artist, album, date, label, genre

2) Filtrado de Fechas
   - Filtra Nov/Dec 2025 + TBA
   - Convierte fechas a ISO
   - 1416 -> 104

3) Por cada álbum (con delay 20s)
   A) iTunes:
      - Busca artista/catálogo (multi-país)
      - Matchea álbum
      - Obtiene cover 1200x1200
      - Fallback a text search
   B) YT Music:
      - Search en ytmusicapi
      - Match por nombre normalizado
      - Extrae browseId

4) Guardar JSON
   - albums_covers.json

5) Seed en Supabase
   - Lee JSON
   - Mapea schema
   - Batch insert
```

---

## Archivos del Proyecto

```
backend/
├── scraper_wikipedia_itunes.py
├── albums_covers.json
├── TEST_COVER.py
├── scripts/
│   └── seed_upcoming_releases.py
├── services/
│   └── supabase_service.py
└── .env
```

---

## Referencias y Recursos

### iTunes Search API
- Docs (Apple): https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/
- Rate limit (Stack Overflow): https://stackoverflow.com/questions/12596300/itunes-search-api-rate-limit
- Base URL: `https://itunes.apple.com/search`

### YT Music API (ytmusicapi)
- Docs: https://ytmusicapi.readthedocs.io/
- GitHub: https://github.com/sigma67/ytmusicapi
- Instalación: `pip install ytmusicapi`

### Apple Developer Forums
- Rate limiting: https://developer.apple.com/forums/thread/66399
- Throttling: https://developer.apple.com/forums/thread/68923

---

## Seguridad y Best Practices

### Variables de entorno

Nunca commitear:
- `.env` con keys reales
- `SUPABASE_KEY` hardcodeada
- credenciales embebidas

Sí commitear:
- `.env.example` con placeholders
- código que lee env vars

### Rate limiting

Siempre:
- respetar delays
- manejar 429 con backoff/retry
- mantenerte bajo 20/min

Nunca:
- requests sin delays
- ignorar rate limits
- saturar el endpoint

### Datos sensibles

En el JSON output:
- URLs públicas y metadata pública
- no guardar tokens ni keys

---

## Estadísticas del Último Run

Ejecución: 31 Octubre 2025

Input:
- Wikipedia: 1,416 álbumes scraped
- Filtrados: 104 (Nov/Dec 2025 + TBA)

Output:
- Covers: 85/104
- Artist IDs: 95/104
- TBA: 18/104

Performance:
- Tiempo total: ~35 minutos
- Delay: 20s
- Rate limit hits: 0
- Errores: 0

---

## Checklist de Ejecución

Antes:
- instalar dependencias
- configurar `.env`
- internet estable
- no estar bloqueado en iTunes (test con `TEST_COVER.py`)
- tener ~40 minutos libres

Scraping:
- correr primero con `--limit 5`
- verificar JSON
- revisar resultados de covers

Seeding:
- correr `--dry-run`
- validar datos
- correr `--clear`
- verificar rows en Supabase

---

## Próximos Pasos

Prioridad alta:
- retry automático ante timeout
- cache de resultados iTunes para evitar re-scrapear
- webhook/notificación de cambios

Prioridad media:
- scraping incremental
- soporte para 2026+
- dashboard de monitoreo

Prioridad baja:
- fallback a Spotify API
- predicción de fechas TBA
- ejecución automática vía CI

---

Última actualización: 25 Febrero 2026  
Versión: 1.0  
Mantenido por: MaxiRebolo