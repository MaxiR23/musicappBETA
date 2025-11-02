# 📚 Documentación: Scraper de Álbumes 2025

## 🎯 Descripción General

Sistema automatizado para obtener información de álbumes que saldrán en noviembre/diciembre 2025, incluyendo:
- Metadata de álbumes desde Wikipedia
- Covers en alta resolución desde iTunes API
- Artist IDs desde YouTube Music API

---

## 📋 Tabla de Contenidos

1. [Requisitos](#requisitos)
2. [Scripts Disponibles](#scripts-disponibles)
3. [Rate Limits de iTunes](#rate-limits-de-itunes)
4. [Uso del Scraper](#uso-del-scraper)
5. [Seedear Base de Datos](#seedear-base-de-datos)
6. [Troubleshooting](#troubleshooting)

---

## 🔧 Requisitos

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

## 📜 Scripts Disponibles

### 1. `scraper_wikipedia_itunes.py`

**Ubicación:** `backend/scraper_wikipedia_itunes.py`

**Función:** Scrapea Wikipedia para obtener álbumes 2025, busca covers en iTunes y artist IDs en YouTube Music.

**Output:** `albums_covers.json` con 104 álbumes

**Características:**
- ✅ Scraping de Wikipedia automático
- ✅ Filtrado de Nov/Dec 2025 + TBA
- ✅ Búsqueda inteligente de covers en iTunes (12 países)
- ✅ Búsqueda de artist IDs en YouTube Music
- ✅ Manejo de rate limits con delays configurables
- ✅ Retry logic para errores 429

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

## ⚠️ Rate Limits de iTunes

### Límite Oficial
**20 requests por minuto por IP** ([Fuente: Apple Docs](https://stackoverflow.com/questions/12596300/itunes-search-api-rate-limit))

### Configuración Actual

```python
DELAY_BETWEEN_ALBUMS = 20.0  # segundos entre álbumes
DELAY_BETWEEN_REQUESTS = 1.5  # segundos entre requests internos
```

### Cálculo de Seguridad

**Con 20 segundos de delay:**
- 3 álbumes/minuto
- ~4-8 requests por álbum
- **Total: 12-24 requests/minuto** ✅ (dentro del límite de 20/min)

**Tiempo total para 104 álbumes:** ~35 minutos

### ⚠️ Configuraciones NO Recomendadas

| Delay | Álbumes/min | Requests/min | Resultado |
|-------|-------------|--------------|-----------|
| 0.5s  | 120         | 480-960      | ❌ BAN en 30s |
| 5s    | 12          | 48-96        | ❌ BAN rápido |
| 10s   | 6           | 24-48        | ⚠️ Riesgoso |
| **20s** | **3**   | **12-24**    | ✅ **SEGURO** |
| 30s   | 2           | 8-16         | ✅✅ Muy seguro |
| 60s   | 1           | 4-8          | ✅✅✅ Ultra seguro |

### Duración del Ban

Si te banean por rate limit:
- **Típico:** 1-2 horas
- **Máximo:** 6-12 horas (si saturaste mucho)
- **Síntomas:** 403 Forbidden en todos los requests

### Soluciones al Ban

1. **Esperar 2 horas** (más fácil)
2. **Cambiar IP:**
   - Reiniciar router (apagar 5 min)
   - Usar VPN (ProtonVPN, Windscribe)
3. **Ejecutar en Google Colab** (IP diferente)

---

## 🚀 Uso del Scraper

### Ejecución Normal

```bash
python scraper_wikipedia_itunes.py
```

**Output esperado:**
```
======================================================================
🎵 SCRAPER DE ÁLBUMES 2025 CON COVERS
⏱️  Delay: 20.0s entre álbumes
======================================================================

🎵 Scrapeando Wikipedia...
✅ Encontrados 1416 álbumes en Wikipedia

🎯 Filtrados Nov/Dec 2025 + TBA: 104 álbumes

⏱️  Tiempo estimado: ~34.7 minutos

🖼️  Buscando covers y artist IDs...
   (con delays de seguridad para evitar rate limits)

[1/104] Juana Molina - Doga ✓ ✓
[2/104] Agnostic Front - Echoes in Eternity ✓ ✓
[3/104] Allie X - Happiness Is Going to Get You ✗ ✓
...
[104/104] Triptykon - TBA ✗ ✓

======================================================================
📊 RESULTADOS:
======================================================================
Total álbumes:          104
Covers encontrados:     85
Artist IDs encontrados: 95
Sin cover:              19
Sin artist ID:          9
======================================================================

💾 Guardado en 'albums_covers.json'
```

### Interpretación de Símbolos

- **✓ ✓** = Cover encontrado + Artist ID encontrado
- **✓ ✗** = Cover encontrado + Sin Artist ID
- **✗ ✓** = Sin cover + Artist ID encontrado
- **✗ ✗** = Sin cover + Sin Artist ID

### Opciones de Línea de Comandos

```bash
# Procesar solo los primeros N álbumes
python scraper_wikipedia_itunes.py --limit 5
```

### Modo Test (en el código)

Para probar con 1 solo álbum, descomentar en `main()`:

```python
albums = albums[:1]
print(f"⚠️  TEST MODE: Procesando solo 1 álbum\n")
```

---

## 💾 Seedear Base de Datos

### Paso 1: Preview (Dry Run)

Siempre hacer primero un dry run para verificar:

```bash
python scripts/seed_upcoming_releases.py albums_covers.json --dry-run
```

**Output esperado:**
```
📖 Leyendo albums_covers.json...
✅ Cargados 104 álbumes del JSON
🎯 Filtrados nov/dic 2025: 104 álbumes

🔍 DRY RUN - No se insertará nada

1. Juana Molina - Doga
   Fecha: 2025-11-05
   Cover: ✓
   Artist ID: ✓

2. Agnostic Front - Echoes in Eternity
   Fecha: 2025-11-07
   Cover: ✓
   Artist ID: ✓

3. Allie X - Happiness Is Going to Get You
   Fecha: 2025-11-07
   Cover: ✗
   Artist ID: ✓

... y 99 más

Total a insertar: 104
✨ Listo!
```

### Paso 2: Insertar en Supabase

Si el dry run se ve bien:

```bash
python scripts/seed_upcoming_releases.py albums_covers.json --clear
```

**Output esperado:**
```
📖 Leyendo albums_covers.json...
✅ Cargados 104 álbumes del JSON
🎯 Filtrados nov/dic 2025: 104 álbumes

⚠️  Borrando contenido existente...
✅ Borrados: OK

📥 Insertando 104 releases...
✅ Insertados: 104

📊 Estadísticas:
   Con cover: 85/104
   Con artist_id: 95/104
   TBA: 18

✨ Listo!
```

### Flags Disponibles

| Flag | Descripción |
|------|-------------|
| `--dry-run` | Preview sin insertar (recomendado primero) |
| `--clear` | Borra releases existentes antes de insertar |
| Sin flags | Inserta sin borrar (puede causar duplicados) |

---

## 🐛 Troubleshooting

### Error: `403 Forbidden` en iTunes

**Síntomas:**
```
[DEBUG] text search failed ar 403
[DEBUG] text search failed mx 403
[DEBUG] text search failed us 403
```

**Causa:** Rate limit excedido - hiciste demasiados requests muy rápido

**Solución:**
1. **Esperar 1-2 horas** (más fácil)
2. **Cambiar IP:**
   ```bash
   # Windows
   ipconfig /release
   ipconfig /renew
   ```
   O reiniciar router (5 min apagado)
3. **Usar VPN** (ProtonVPN, Windscribe)
4. **Ejecutar en Google Colab** (IP diferente)

**Prevención:**
- No cambiar `DELAY_BETWEEN_ALBUMS` a menos de 20s
- Si te banearon, usa 30s en el próximo run

---

### Error: `ModuleNotFoundError: No module named 'ytmusicapi'`

**Causa:** Falta instalar dependencia

**Solución:**
```bash
pip install ytmusicapi
```

O instalar todas:
```bash
pip install requests beautifulsoup4 httpx ytmusicapi
```

---

### Error: Algunos álbumes sin cover

**Síntomas:**
```
[27/104] Stella Donnelly - Love and Fortune ✗ ✓
[28/104] Teen Jesus - Glory ✗ ✓
```

**Causa:** Álbumes futuros que todavía no están en iTunes

**Solución:** 
- **Normal y esperado** - Estos álbumes se salvan igual con `thumbnail_url: null`
- iTunes publicará los covers más cerca de la fecha de lanzamiento
- Podés re-scrapear en diciembre para obtener los covers faltantes

**¿Es problema?** No, la app funciona igual. Solo no mostrarán imagen.

---

### Error: `artist not found at all`

**Causas posibles:**
1. Artista no existe en iTunes (muy indie/nuevo)
2. Nombre mal escrito en Wikipedia
3. Artista solo en plataformas alternativas

**Solución:** 
- El script continúa automáticamente
- Se guarda sin cover pero con artist_id si está en YouTube Music
- No es un error crítico

---

### Script muy lento

**Causa:** Delays de seguridad activados (INTENCIONAL)

**Info:** 
- Con 20s de delay, 104 álbumes toman ~35 minutos
- Esto es **correcto y necesario** para evitar rate limits
- **NO reducir el delay** a menos que quieras arriesgarte a un ban

**Alternativa si tenés prisa:**
- Ejecutar en Google Colab (IP diferente, podés correr múltiples instancias)

---

### Error: `SUPABASE_URL` not found

**Causa:** Variables de entorno no configuradas

**Solución:**
Crear/actualizar `.env`:
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
1. Verificar conexión a internet
2. Reintentar más tarde
3. Verificar que no haya firewall bloqueando Python

---

## 📊 Estructura del JSON Output

### Ejemplo Completo

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

### Campos Requeridos

Siempre presentes:
- `release_date` (string: "YYYY-MM-DD" o "TBA")
- `artist` (string)
- `album` (string)

### Campos Opcionales

Pueden ser `null` o no estar presentes:
- `label` (string)
- `genre` (string)
- `thumbnail` (string URL)
- `track_count` (number)
- `artist_id` (string - YouTube Music browseId)

### Mapeo a Base de Datos

El script `seed_upcoming_releases.py` mapea automáticamente:

| JSON | Supabase Column | Tipo |
|------|----------------|------|
| `artist` | `artist_name` | text |
| `album` | `album_name` | text |
| `release_date` | `release_date` | date (null si TBA) |
| `release_date == "TBA"` | `is_tba` | boolean |
| `label` | `label` | text |
| `thumbnail` | `thumbnail_url` | text |
| `track_count` | `track_count` | integer |
| `artist_id` | `artist_id` | text |

---

## 🔄 Actualización Futura

### Mediados de Diciembre 2025

**TODO:** Actualizar el filtro para incluir primeros 6 meses de 2026.

Buscar esta función en `scraper_wikipedia_itunes.py`:

```python
def filter_nov_dec_2025(albums):
    """
    Filters only November/December 2025 albums + TBA
    
    TODO: Mid-December 2025 - Update this to include first 6 months of 2026
          Change filter to: 2025-11, 2025-12, 2026-01, 2026-02, 2026-03, 2026-04, 2026-05, 2026-06
    """
    filtered = []
    for album in albums:
        release_date = album.get('release_date', '')
        
        # Include TBA albums
        if release_date == 'TBA':
            filtered.append(album)
            continue
        
        # ACTUALIZAR ESTOS MESES:
        if release_date and isinstance(release_date, str):
            if release_date.startswith('2025-11') or release_date.startswith('2025-12'):
                filtered.append(album)
    
    return filtered
```

**Cambiar a:**

```python
def filter_upcoming_releases(albums):
    """
    Filters upcoming releases (Nov/Dec 2025 + First half 2026)
    """
    filtered = []
    for album in albums:
        release_date = album.get('release_date', '')
        
        if release_date == 'TBA':
            filtered.append(album)
            continue
        
        # Meses válidos
        valid_months = [
            '2025-11', '2025-12',
            '2026-01', '2026-02', '2026-03', 
            '2026-04', '2026-05', '2026-06'
        ]
        
        if any(release_date.startswith(month) for month in valid_months):
            filtered.append(album)
    
    return filtered
```

---

## 📝 Notas Importantes

### Covers Faltantes (~15-20%)

**Es normal que algunos álbumes no tengan cover porque:**
- Son releases futuros no publicados aún en iTunes
- Artistas muy pequeños/indie sin distribución digital
- Pre-orders sin metadata completa
- Restricciones regionales

**¿Qué hacer?**
- Los álbumes se guardan igual con `thumbnail_url: null`
- La app debe manejar casos sin imagen (placeholder)
- Re-scrapear en diciembre para actualizar covers

### Artist IDs Faltantes (~5-10%)

**Es normal que algunos artistas no tengan artist_id porque:**
- Artista no está en YouTube Music
- Nombre mal formateado (ej: "Bell Witchand Aerial Ruin" - nombre compuesto)
- Artista muy nuevo/indie

**¿Qué hacer?**
- Se guarda con `artist_id: null`
- Features que necesiten YouTube Music ID no funcionarán para esos artistas

### Álbumes TBA

**Info:**
- ~17% de álbumes son TBA (sin fecha específica)
- Se marcan con `is_tba: true` en la DB
- Útil para "próximamente" sin fecha exacta

### Performance

**Optimizaciones implementadas:**
- ✅ Batch insert en Supabase (1 request para 104 álbumes)
- ✅ Cache interno de búsquedas de artistas
- ✅ Búsqueda multi-país (prioriza US, luego otros)
- ✅ Fallback a búsqueda de texto si falla catálogo
- ✅ Manejo inteligente de rate limits (429)

---

## 🎓 Flujo Completo del Sistema

```
┌─────────────────────────────────────────────────────────┐
│  1. Wikipedia Scraping                                  │
│     - Scrapea https://en.wikipedia.org/wiki/           │
│       List_of_2025_albums                               │
│     - Parsea tablas HTML                                │
│     - Extrae: artist, album, date, label, genre        │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  2. Filtrado de Fechas                                  │
│     - Filtra Nov/Dec 2025 + TBA                        │
│     - Convierte fechas a ISO format                     │
│     - 1416 álbumes → 104 álbumes                       │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  3. Para cada álbum (con delays de 20s):               │
│                                                          │
│  A. Buscar cover en iTunes:                            │
│     ├─ Buscar artist_id en iTunes (12 países)          │
│     ├─ Obtener catálogo del artista (200 álbumes)      │
│     ├─ Matchear álbum específico (strict)              │
│     ├─ Obtener cover en 1200x1200px                    │
│     └─ Fallback: búsqueda por texto si falla           │
│                                                          │
│  B. Buscar artist_id en YouTube Music:                 │
│     ├─ Search en YT Music API                          │
│     ├─ Match por nombre normalizado                    │
│     └─ Extraer browseId                                │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  4. Guardar JSON                                        │
│     - albums_covers.json (104 álbumes)                  │
│     - ~85 con cover                                     │
│     - ~95 con artist_id                                 │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  5. Seedear en Supabase                                 │
│     - Leer albums_covers.json                           │
│     - Mapear a schema de DB                             │
│     - Batch insert (1 request)                          │
│     - Tabla: upcoming_releases                          │
└─────────────────────────────────────────────────────────┘
                        ↓
                   ✅ Done!
```

---

## 📦 Archivos del Proyecto

```
backend/
├── scraper_wikipedia_itunes.py       # Script principal de scraping
├── albums_covers.json                 # Output del scraper (104 álbumes)
├── TEST_COVER.py                      # Script de testing para iTunes
├── scripts/
│   └── seed_upcoming_releases.py     # Seeder para Supabase
├── services/
│   └── supabase_service.py           # Cliente de Supabase
└── .env                              # Variables de entorno
```

---

## 📞 Referencias y Recursos

### APIs Utilizadas

- **iTunes Search API**
  - Docs: https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/
  - Rate Limits: https://stackoverflow.com/questions/12596300/itunes-search-api-rate-limit
  - Base URL: `https://itunes.apple.com/search`

- **YouTube Music API (ytmusicapi)**
  - Docs: https://ytmusicapi.readthedocs.io/
  - GitHub: https://github.com/sigma67/ytmusicapi
  - Instalación: `pip install ytmusicapi`

### Stack Overflow

- Rate Limit Discussion: https://stackoverflow.com/questions/12596300/itunes-search-api-rate-limit
- Rate Limit per Device: https://stackoverflow.com/questions/41290585/is-itunes-search-api-rate-limit-per-device-or-per-app

### Apple Developer Forums

- Search API Rate Limiting: https://developer.apple.com/forums/thread/66399
- Throttling Issues: https://developer.apple.com/forums/thread/68923

---

## 🔐 Seguridad y Best Practices

### Variables de Entorno

**NUNCA commitear:**
- ❌ `.env` con keys reales
- ❌ `SUPABASE_KEY` en código
- ❌ Credentials hardcodeadas

**SÍ commitear:**
- ✅ `.env.example` con placeholders
- ✅ Código que lee de variables de entorno

### Rate Limiting

**SIEMPRE:**
- ✅ Respetar delays configurados
- ✅ Manejar errores 429 gracefully
- ✅ Implementar retry logic con backoff

**NUNCA:**
- ❌ Hacer requests sin delays
- ❌ Ignorar errores de rate limit
- ❌ Hacer más de 20 requests/min a iTunes

### Datos Sensibles

**En el JSON output:**
- ✅ URLs públicas (covers, artistas)
- ✅ Metadata pública (nombres, fechas)
- ❌ User tokens o private keys

---

## 📈 Estadísticas del Último Run

### Ejecución: 31 Octubre 2025

**Input:**
- Wikipedia: 1,416 álbumes scraped
- Filtrados: 104 álbumes (Nov/Dec 2025 + TBA)

**Output:**
- Covers encontrados: 85/104 (82%)
- Artist IDs encontrados: 95/104 (91%)
- Albums TBA: 18/104 (17%)

**Performance:**
- Tiempo total: ~35 minutos
- Delay entre álbumes: 20 segundos
- Rate limit hits: 0 ✅
- Errores: 0 ✅

**Distribución por mes:**
- Noviembre 2025: 68 álbumes
- Diciembre 2025: 18 álbumes
- TBA: 18 álbumes

---

## ✅ Checklist de Ejecución

Antes de correr el scraper completo:

- [ ] Instalar dependencias (`pip install ...`)
- [ ] Configurar `.env` con Supabase credentials
- [ ] Verificar conexión a internet estable
- [ ] Confirmar que no estés baneado de iTunes (test con `TEST_COVER.py`)
- [ ] Tener ~40 minutos libres (para 104 álbumes)

Para el scraping:

- [ ] Correr primero con `--limit 5` para testear
- [ ] Verificar que el JSON se genera correctamente
- [ ] Revisar que los covers se estén descargando

Para el seeding:

- [ ] Correr `--dry-run` primero para preview
- [ ] Verificar que los datos se vean correctos
- [ ] Correr con `--clear` para insertar
- [ ] Verificar en Supabase que se insertaron 104 rows

---

## 🎯 Próximos Pasos

### Mejoras Futuras

**Prioridad Alta:**
- [ ] Implementar retry automático en caso de timeout
- [ ] Cache de resultados de iTunes (evitar re-scrapear álbumes ya procesados)
- [ ] Webhook para notificar cuando nuevos álbumes aparezcan en Wikipedia

**Prioridad Media:**
- [ ] Scraping incremental (solo álbumes nuevos)
- [ ] Support para otros meses (2026+)
- [ ] Dashboard para monitorear scraping en tiempo real

**Prioridad Baja:**
- [ ] Soporte para Spotify API como fallback
- [ ] Machine learning para predecir fechas de álbumes TBA
- [ ] Auto-ejecución semanal vía GitHub Actions

---

**Última actualización:** 31 Octubre 2025  
**Versión:** 1.0  
**Mantenido por:** MaxiRebolo

---

**¿Preguntas? ¿Bugs? ¿Sugerencias?**  
Crear un issue en el repo o contactar al equipo de desarrollo.