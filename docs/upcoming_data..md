-- Tabla única para releases de nov/dic 2025
CREATE TABLE upcoming_releases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  
  -- Info del artista
  artist_name TEXT NOT NULL,
  artist_id TEXT, -- YouTube Music browseId (puede ser NULL)
  
  -- Info del álbum
  album_name TEXT NOT NULL,
  release_date DATE, -- NULL si es TBA
  is_tba BOOLEAN DEFAULT FALSE,
  label TEXT,
  thumbnail_url TEXT,
  track_count INTEGER,
  
  -- Timestamps
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para performance
CREATE INDEX idx_upcoming_releases_date 
  ON upcoming_releases(release_date) 
  WHERE release_date IS NOT NULL;

CREATE INDEX idx_upcoming_releases_tba 
  ON upcoming_releases(is_tba) 
  WHERE is_tba = TRUE;

CREATE INDEX idx_upcoming_releases_artist_name 
  ON upcoming_releases(artist_name);

-- Auto-update del campo updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER releases_updated_at 
  BEFORE UPDATE ON upcoming_releases
  FOR EACH ROW 
  EXECUTE FUNCTION update_updated_at();


## EXTRA DATA:

Cómo usar el script:
1. Asegurate que tenés el JSON generado por tu scraper:
bash# Ejecutá tu scraper primero (en tu máquina local)
python scraper_albums.py
# Esto genera: albums_with_covers.json
2. Dry-run (para ver qué va a hacer sin insertar):
bashpython scripts/seed_upcoming_releases.py albums_with_covers.json --dry-run
3. Insertar de verdad:
bashpython scripts/seed_upcoming_releases.py albums_with_covers.json
4. Si querés borrar todo y empezar de cero:
bashpython scripts/seed_upcoming_releases.py albums_with_covers.json --clear
```

---

## Output esperado:
```
📖 Leyendo albums_with_covers.json...
✅ Cargados 1234 álbumes del JSON
🎯 Filtrados nov/dic 2025: 156 álbumes

📥 Insertando 156 releases...
✅ Insertados: 156

📊 Estadísticas:
   Con cover: 142/156
   Con artist_id: 150/156
   TBA: 12

✨ Listo!


#### COLAB
# ============================================================================
# SCRAPER DE ÁLBUMES 2025 - GOOGLE COLAB VERSION
# ============================================================================
# Instrucciones:
# 1. Copiar TODO este código en una celda de Colab
# 2. Run (Ctrl+Enter)
# 3. Esperar ~35 minutos
# 4. Descargar albums_covers.json automáticamente
# ============================================================================

# PASO 1: Instalar dependencias
print("📦 Instalando dependencias...")
!pip install -q requests beautifulsoup4 ytmusicapi

import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
import unicodedata
import time
from ytmusicapi import YTMusic
import json

# ============================================================================
# CONFIGURACIÓN
# ============================================================================
DELAY_BETWEEN_ALBUMS = 20.0  # ⚠️ 20 segundos entre álbumes
DELAY_BETWEEN_REQUESTS = 1.5  # Delay interno entre requests
DEFAULT_COVER_SIZE = 1200
SHOW_DEBUG = False
TEST_MODE = False  # Cambiar a True para probar con solo 3 álbumes
TEST_LIMIT = 3

# ============================================================================
# FUNCIONES DE SCRAPING (Wikipedia)
# ============================================================================

def clean_text(text):
    return re.sub(r'\[\d+\]', '', text).strip()

def parse_date_to_iso(date_str):
    if not date_str or date_str == 'TBA':
        return date_str
    try:
        date_obj = datetime.strptime(f"{date_str} 2025", "%B%d %Y")
        return date_obj.strftime("%Y-%m-%d")
    except:
        return date_str

def parse_dated_albums(table, current_date=None):
    albums = []
    for row in table.find_all('tr')[1:]:
        cols = row.find_all(['td', 'th'])
        if len(cols) == 0:
            continue
        
        first_text = cols[0].get_text(strip=True)
        is_date = any(month in first_text for month in ['January', 'February', 'March', 'April', 
                                                          'May', 'June', 'July', 'August', 
                                                          'September', 'October', 'November', 'December'])
        
        if cols[0].has_attr('rowspan') or is_date:
            current_date = first_text
            artist = cols[1].get_text(strip=True) if len(cols) > 1 else ''
            album = cols[2].get_text(strip=True) if len(cols) > 2 else ''
            genre = cols[3].get_text(strip=True) if len(cols) > 3 else ''
            label = cols[4].get_text(strip=True) if len(cols) > 4 else ''
        else:
            artist = cols[0].get_text(strip=True) if len(cols) > 0 else ''
            album = cols[1].get_text(strip=True) if len(cols) > 1 else ''
            genre = cols[2].get_text(strip=True) if len(cols) > 2 else ''
            label = cols[3].get_text(strip=True) if len(cols) > 3 else ''
        
        if artist and album:
            artist = clean_text(artist)
            album = clean_text(album)
            genre = clean_text(genre)
            label = clean_text(label)
            
            # Validaciones
            if not current_date or current_date == 'None':
                continue
            if not any(month in current_date for month in ['January', 'February', 'March', 'April', 
                                                             'May', 'June', 'July', 'August', 
                                                             'September', 'October', 'November', 'December']):
                continue
            if artist in ['TBA', 'Artist', 'None', '', 'Release date']:
                continue
            if album in ['TBA', 'Album', 'None', '', 'Artist']:
                continue
            if any(month in artist for month in ['January', 'February', 'March', 'April', 'May', 'June', 
                                                   'July', 'August', 'September', 'October', 'November', 'December']):
                continue
            
            formatted_date = parse_date_to_iso(current_date)
            
            album_data = {
                'release_date': formatted_date,
                'artist': artist,
                'album': album
            }
            
            if genre:
                album_data['genre'] = genre
            if label:
                album_data['label'] = label
            
            albums.append(album_data)
    
    return albums

def parse_tba_albums(table):
    albums = []
    for row in table.find_all('tr')[1:]:
        cols = row.find_all(['td', 'th'])
        if len(cols) < 2:
            continue
        
        artist = cols[0].get_text(strip=True)
        album = cols[1].get_text(strip=True) if len(cols) > 1 else ''
        genre = cols[2].get_text(strip=True) if len(cols) > 2 else ''
        label = cols[3].get_text(strip=True) if len(cols) > 3 else ''
        
        if artist and album:
            artist = clean_text(artist)
            album = clean_text(album)
            genre = clean_text(genre)
            label = clean_text(label)
            
            if artist in ['Artist', 'None', '']:
                continue
            if album in ['Album', 'None', '']:
                continue
            
            album_data = {
                'release_date': 'TBA',
                'artist': artist,
                'album': album
            }
            
            if genre and genre != 'TBA':
                album_data['genre'] = genre
            if label and label != 'TBA':
                album_data['label'] = label
            
            albums.append(album_data)
    
    return albums

def scrape_wikipedia_albums():
    print("🎵 Scrapeando Wikipedia...")
    url = "https://en.wikipedia.org/wiki/List_of_2025_albums"
    response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(response.content, 'html.parser')
    
    dated_albums = []
    tba_albums = []
    tba_started = False
    
    for element in soup.find_all(['table', 'h2', 'h3']):
        if element.name in ['h2', 'h3']:
            heading_text = element.get_text(strip=True)
            if 'TBA' in heading_text or 'Unreleased' in heading_text:
                tba_started = True
        elif element.name == 'table' and 'wikitable' in element.get('class', []):
            if tba_started:
                tba_albums.extend(parse_tba_albums(element))
            else:
                dated_albums.extend(parse_dated_albums(element))
    
    return dated_albums + tba_albums

def filter_nov_dec_2025(albums):
    filtered = []
    for album in albums:
        release_date = album.get('release_date', '')
        if release_date == 'TBA':
            filtered.append(album)
            continue
        if release_date and isinstance(release_date, str):
            if release_date.startswith('2025-11') or release_date.startswith('2025-12'):
                filtered.append(album)
    return filtered

# ============================================================================
# FUNCIONES DE COVER (iTunes/Apple Music)
# ============================================================================

UA = {"User-Agent": "Mozilla/5.0"}
ITUNES_SEARCH = "https://itunes.apple.com/search"
ITUNES_LOOKUP = "https://itunes.apple.com/lookup"
COUNTRIES = ["us", "ar", "mx", "es", "gb"]  # Reducido para Colab

def norm(s):
    s = (s or "").strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\b(deluxe|clean|remaster(ed)?|remix(es)?|expanded|edition)\b", "", s).strip()
    return s

def upscale(url, size=1200):
    if not url: 
        return None
    return (url
        .replace("60x60bb", f"{size}x{size}bb")
        .replace("100x100bb", f"{size}x{size}bb")
        .replace("1400x1400bb", f"{size}x{size}bb"))

def search_artist_id(artist):
    aq = norm(artist)
    for country in COUNTRIES:
        try:
            time.sleep(DELAY_BETWEEN_REQUESTS)
            r = requests.get(ITUNES_SEARCH, params={
                "term": artist, 
                "entity": "musicArtist", 
                "limit": 10, 
                "country": country
            }, headers=UA, timeout=10)
            
            if r.status_code == 429:
                time.sleep(10)
                continue
            if r.status_code != 200:
                continue
                
            for it in r.json().get("results", []):
                if norm(it.get("artist_name", "")) == aq:
                    return (str(it.get("artist_id")), country)
        except:
            continue
    return None

def lookup_artist_albums(artist_id, country):
    time.sleep(DELAY_BETWEEN_REQUESTS)
    try:
        r = requests.get(ITUNES_LOOKUP, params={
            "id": artist_id,
            "entity": "album",
            "limit": 200,
            "country": country,
        }, headers=UA, timeout=10)
        
        if r.status_code == 200:
            return [x for x in r.json().get("results", []) if x.get("wrapperType") == "collection"]
    except:
        pass
    return []

def strict_pick_album(albums, artist, album):
    aq, tq = norm(artist), norm(album)
    albums = [x for x in albums if x.get("collectionType") == "Album"]
    if not albums: 
        return None

    def score(x):
        an = norm(x.get("artist_name", ""))
        tn = norm(x.get("collectionName", ""))
        exact_title = int(tn == tq)
        starts_title = int(tn.startswith(tq))
        contains_title = int(tq in tn)
        exact_artist = int(an == aq)
        cid = int(x.get("collectionId", 0))
        rdate = x.get("releaseDate", "")
        return (exact_artist, exact_title, starts_title, contains_title, rdate, cid)

    albums.sort(key=score, reverse=True)
    top = albums[0]
    a_ok = (norm(top.get("artist_name", "")) == aq)
    t_ok = (norm(top.get("collectionName", "")) == tq)
    ts_ok = norm(top.get("collectionName", "")).startswith(tq)
    
    if not (a_ok and (t_ok or ts_ok)):
        return None
    return top

def get_album_cover(artist, album, size=DEFAULT_COVER_SIZE):
    artist_found = search_artist_id(artist)
    if not artist_found:
        return None
    
    artist_id, country = artist_found
    albums = lookup_artist_albums(artist_id, country)
    if not albums:
        return None
    
    pick = strict_pick_album(albums, artist, album)
    if not pick:
        return None
    
    cid = pick.get("collectionId")
    if not cid:
        return None
    
    time.sleep(DELAY_BETWEEN_REQUESTS)
    try:
        r = requests.get(ITUNES_LOOKUP, params={
            "id": cid, 
            "country": country
        }, headers=UA, timeout=10)
        
        if r.status_code == 200:
            items = r.json().get("results", [])
            if items:
                art = (items[0].get("artworkUrl100") or 
                       items[0].get("artworkUrl60") or 
                       items[0].get("artworkUrl512"))
                track_count = items[0].get("trackCount")
                if art:
                    return {
                        "thumbnail": upscale(art, size), 
                        "track_count": track_count
                    }
    except:
        pass
    return None

# ============================================================================
# FUNCIONES DE YOUTUBE MUSIC
# ============================================================================

def get_youtube_artist_id(artist):
    try:
        ytmusic = YTMusic()
        results = ytmusic.search(artist, filter='artists', limit=5)
        if not results:
            return None
        
        artist_norm = norm(artist)
        for result in results:
            result_name = result.get('artist', '')
            if norm(result_name) == artist_norm:
                return result.get('browseId')
        
        return results[0].get('browseId')
    except:
        return None

# ============================================================================
# FUNCIÓN PRINCIPAL
# ============================================================================

print("="*70)
print("🎵 SCRAPER DE ÁLBUMES 2025 CON COVERS - COLAB VERSION")
print(f"⏱️  Delay: {DELAY_BETWEEN_ALBUMS}s entre álbumes")
print("="*70)
print()

# Paso 1: Scraper Wikipedia
albums = scrape_wikipedia_albums()
print(f"✅ Encontrados {len(albums)} álbumes en Wikipedia\n")

# Paso 2: Filtrar
albums = filter_nov_dec_2025(albums)
print(f"🎯 Filtrados Nov/Dec 2025 + TBA: {len(albums)} álbumes\n")

# TEST MODE (opcional)
if TEST_MODE:
    albums = albums[:TEST_LIMIT]
    print(f"⚠️  TEST MODE: Procesando solo {TEST_LIMIT} álbumes\n")

# Calcular tiempo
estimated_time = len(albums) * DELAY_BETWEEN_ALBUMS / 60
print(f"⏱️  Tiempo estimado: ~{estimated_time:.1f} minutos\n")

# Paso 3: Buscar covers y artist IDs
print("🖼️  Buscando covers y artist IDs...")
print("   (con delays de seguridad)\n")

found_covers = 0
found_artist_ids = 0

for i, album in enumerate(albums, 1):
    print(f"[{i}/{len(albums)}] {album['artist']} - {album['album']}", end=" ", flush=True)
    
    # Buscar cover
    try:
        cover_data = get_album_cover(album['artist'], album['album'])
        if cover_data:
            album['thumbnail'] = cover_data['thumbnail']
            album['track_count'] = cover_data['track_count']
            found_covers += 1
            print("✓", end=" ", flush=True)
        else:
            print("✗", end=" ", flush=True)
    except Exception as e:
        print("✗", end=" ", flush=True)
    
    # Buscar artist_id
    try:
        artist_id = get_youtube_artist_id(album['artist'])
        if artist_id:
            album['artist_id'] = artist_id
            found_artist_ids += 1
            print("✓")
        else:
            print("✗")
    except:
        print("✗")
    
    # Delay entre álbumes
    if i < len(albums):
        time.sleep(DELAY_BETWEEN_ALBUMS)

print()
print("="*70)
print("📊 RESULTADOS:")
print("="*70)
print(f"Total álbumes:          {len(albums)}")
print(f"Covers encontrados:     {found_covers}")
print(f"Artist IDs encontrados: {found_artist_ids}")
print(f"Sin cover:              {len(albums) - found_covers}")
print(f"Sin artist ID:          {len(albums) - found_artist_ids}")
print("="*70)
print()

# Guardar JSON
output_file = 'albums_covers.json'
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(albums, f, indent=2, ensure_ascii=False)

print(f"💾 Guardado en '{output_file}'")

# Descargar automáticamente
from google.colab import files
files.download(output_file)

print()
print("✅ ¡COMPLETADO! El archivo debería descargarse automáticamente.")
print("   Si no se descarga, búscalo en Files (panel izquierdo)")