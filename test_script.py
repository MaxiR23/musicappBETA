#!/usr/bin/env python3
"""
Script combinado: Scrapea álbumes de Wikipedia 2025 + busca covers en iTunes

Dependencias:
pip install requests beautifulsoup4 httpx ytmusicapi
"""

import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
import httpx
import unicodedata
import sys
import time
from ytmusicapi import YTMusic

# ============================================================================
# CONFIGURACIÓN
# ============================================================================
SHOW_DEBUG = False  # Cambiar a True para ver logs detallados de iTunes
DELAY_BETWEEN_ALBUMS = 20.0  # ⚠️ 20 SEGUNDOS entre álbumes (anti-rate-limit)
DELAY_BETWEEN_REQUESTS = 1.5  # Delay interno entre requests de iTunes
DEFAULT_COVER_SIZE = 1200  # tamaño del cover en píxeles

# ============================================================================
# FUNCIONES DE SCRAPING (Wikipedia)
# ============================================================================

def clean_text(text):
    """Limpia referencias [1], [2], etc"""
    return re.sub(r'\[\d+\]', '', text).strip()

def parse_date_to_iso(date_str):
    """Convierte 'December12' a '2025-12-12'"""
    if not date_str or date_str == 'TBA':
        return date_str
    
    try:
        date_obj = datetime.strptime(f"{date_str} 2026", "%B%d %Y")
        return date_obj.strftime("%Y-%m-%d")
    except:
        return date_str

def parse_dated_albums(table, current_date=None):
    """Parsea álbumes con fecha definida"""
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
    """Parsea álbumes TBA (sin fecha definida)"""
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
    """Scrapea todos los álbumes de Wikipedia segun el año que estamos"""
    print("🎵 Scrapeando Wikipedia...")
    
    url = "https://en.wikipedia.org/wiki/List_of_2026_albums"
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
    
    all_albums = dated_albums + tba_albums
    return all_albums

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
        
        # Include albums from November/December 2025
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
COUNTRIES = ["ar","mx","us","es","gb","br","fr","de","it","pt","ca","au"]

def dbg(*a):
    if SHOW_DEBUG:
        print("[DEBUG]", *a, file=sys.stderr, flush=True)

def norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\b(deluxe|clean|remaster(ed)?|remix(es)?|expanded|edition)\b", "", s).strip()
    return s

def upscale(url: str, size: int = 1200) -> str | None:
    if not url: 
        return None
    return (url
        .replace("60x60bb", f"{size}x{size}bb")
        .replace("100x100bb", f"{size}x{size}bb")
        .replace("1400x1400bb", f"{size}x{size}bb"))

def search_artist_id(artist: str) -> tuple[str,str] | None:
    aq = norm(artist)
    exacts = []
    with httpx.Client(headers=UA, timeout=20, follow_redirects=True) as c:
        for country in COUNTRIES:
            try:
                time.sleep(DELAY_BETWEEN_REQUESTS)  # ⚠️ Delay entre requests
                r = c.get(ITUNES_SEARCH, params={
                    "term": artist, "entity": "musicArtist", "limit": 10, "country": country
                })
                if r.status_code == 429:  # Rate limit
                    dbg(f"Rate limit en {country}, esperando 10s...")
                    time.sleep(10)
                    continue
                if r.status_code != 200:
                    continue
                for it in r.json().get("results", []):
                    if norm(it.get("artist_name","")) == aq:
                        exacts.append((it, country))
            except:
                continue

        if not exacts:
            best = None
            for country in COUNTRIES:
                try:
                    time.sleep(DELAY_BETWEEN_REQUESTS)
                    r = c.get(ITUNES_SEARCH, params={
                        "term": artist, "entity": "musicArtist", "limit": 10, "country": country
                    })
                    if r.status_code == 429:
                        time.sleep(10)
                        continue
                    if r.status_code != 200: 
                        continue
                    items = r.json().get("results", [])
                    if items:
                        items.sort(key=lambda x: int(x.get("artist_id",0)), reverse=True)
                        best = (items[0], country)
                        break
                except:
                    continue
            return (str(best[0]["artist_id"]), best[1]) if best else None

        seen = {}
        for it, country in exacts:
            seen.setdefault(str(it.get("artist_id")), (it, set()))
            seen[str(it.get("artist_id"))][1].add(country)

        def albums_count(artist_id: str, pref_country: str) -> tuple[int, str, int]:
            for cc in ("us", pref_country):
                try:
                    time.sleep(DELAY_BETWEEN_REQUESTS)
                    r = c.get(ITUNES_LOOKUP, params={
                        "id": artist_id, "entity": "album", "limit": 200, "country": cc
                    })
                    if r.status_code != 200:
                        continue
                    albums = [x for x in r.json().get("results", []) 
                              if x.get("wrapperType")=="collection" and x.get("collectionType")=="Album"]
                    max_cid = max([int(x.get("collectionId",0)) for x in albums], default=0)
                    return (len(albums), cc, max_cid)
                except:
                    continue
            return (0, pref_country, 0)

        scored = []
        for aid, (it, countries) in seen.items():
            cnt, used_cc, max_cid = albums_count(aid, next(iter(countries)))
            score = (cnt, int(used_cc=="us"), max_cid)
            scored.append((score, aid, used_cc))

        scored.sort(reverse=True)
        _, aid, cc = scored[0]
        return aid, cc

def lookup_artist_albums(artist_id: str, country: str) -> list[dict]:
    with httpx.Client(headers=UA, timeout=20, follow_redirects=True) as c:
        time.sleep(DELAY_BETWEEN_REQUESTS)
        r = c.get(ITUNES_LOOKUP, params={
            "id": artist_id,
            "entity": "album",
            "limit": 200,
            "country": country,
        })
        r.raise_for_status()
        rows = [x for x in r.json().get("results", []) if x.get("wrapperType")=="collection"]
        dbg("albums in", country, ":", len(rows))
        return rows

def strict_pick_album(albums: list[dict], artist: str, album: str) -> dict | None:
    aq, tq = norm(artist), norm(album)
    albums = [x for x in albums if x.get("collectionType")=="Album"]
    dbg("albums after type==Album:", len(albums))
    if not albums: 
        return None

    def score(x: dict):
        an = norm(x.get("artist_name",""))
        tn = norm(x.get("collectionName",""))
        exact_title = int(tn == tq)
        starts_title = int(tn.startswith(tq))
        contains_title = int(tq in tn)
        exact_artist = int(an == aq)
        cid = int(x.get("collectionId",0))
        rdate = x.get("releaseDate","")
        return (exact_artist, exact_title, starts_title, contains_title, rdate, cid)

    albums.sort(key=score, reverse=True)
    top = albums[0]
    a_ok = (norm(top.get("artist_name","")) == aq)
    t_ok = (norm(top.get("collectionName","")) == tq)
    ts_ok = norm(top.get("collectionName","")).startswith(tq)
    if not (a_ok and (t_ok or ts_ok)):
        dbg("top candidate rejected by strict check")
        return None
    dbg("top candidate ACCEPTED")
    return top

def apple_cover_by_artist_catalog(artist: str, album: str, size: int) -> dict | None:
    artist_found = search_artist_id(artist)
    if not artist_found:
        dbg("artist not found at all")
        return None
    artist_id, hint = artist_found
    order = [hint] + [c for c in COUNTRIES if c != hint]
    with httpx.Client(headers=UA, timeout=20, follow_redirects=True) as c:
        for country in order:
            try:
                albums = lookup_artist_albums(artist_id, country)
            except Exception as e:
                dbg("lookup albums error", country, repr(e))
                continue
            pick = strict_pick_album(albums, artist, album)
            if not pick:
                dbg("no acceptable album in", country)
                continue
            cid = pick.get("collectionId")
            if not cid:
                dbg("missing collectionId in pick", country)
                continue
            time.sleep(DELAY_BETWEEN_REQUESTS)
            r = c.get(ITUNES_LOOKUP, params={"id": cid, "country": country})
            if r.status_code != 200:
                dbg("final lookup failed", country, r.status_code)
                continue
            items = r.json().get("results", [])
            if not items:
                dbg("final lookup empty", country)
                continue
            art = items[0].get("artworkUrl100") or items[0].get("artworkUrl60") or items[0].get("artworkUrl512")
            track_count = items[0].get("trackCount")
            if art:
                url = upscale(art, size)
                dbg("OK cover from", country, "=>", url, "trackCount=", track_count)
                return {"thumbnail": url, "track_count": track_count}
    return None

def apple_cover_by_text_search(artist: str, album: str, size: int) -> dict | None:
    aq, tq = norm(artist), norm(album)
    with httpx.Client(headers=UA, timeout=20, follow_redirects=True) as c:
        for country in COUNTRIES:
            try:
                time.sleep(DELAY_BETWEEN_REQUESTS)
                r = c.get(ITUNES_SEARCH, params={
                    "term": f"{artist} {album}",
                    "media":"music",
                    "entity":"album",
                    "limit":200,
                    "country": country
                })
                if r.status_code == 429:
                    time.sleep(10)
                    continue
                if r.status_code != 200:
                    dbg("text search failed", country, r.status_code)
                    continue
                results = [x for x in r.json().get("results", []) if x.get("collectionType")=="Album"]
                dbg("text search albums in", country, ":", len(results))
                if not results:
                    continue
                def score(x: dict):
                    an = norm(x.get("artist_name","")); tn = norm(x.get("collectionName",""))
                    exact_title = int(tn == tq)
                    starts_title = int(tn.startswith(tq))
                    contains_title = int(tq in tn)
                    exact_artist = int(an == aq)
                    cid = int(x.get("collectionId",0))
                    rdate = x.get("releaseDate","")
                    return (exact_artist, exact_title, starts_title, contains_title, rdate, cid)
                results.sort(key=score, reverse=True)
                top = results[0]
                a_ok = (norm(top.get("artist_name","")) == aq)
                t_ok = (norm(top.get("collectionName","")) == tq)
                ts_ok = norm(top.get("collectionName","")).startswith(tq)
                if not (a_ok and (t_ok or ts_ok)):
                    dbg("text top rejected by strict check")
                    continue
                cid = top.get("collectionId")
                if not cid:
                    dbg("text top missing cid")
                    continue
                time.sleep(DELAY_BETWEEN_REQUESTS)
                r2 = c.get(ITUNES_LOOKUP, params={"id": cid, "country": country})
                if r2.status_code != 200:
                    dbg("text final lookup failed", country, r2.status_code)
                    continue
                items = r2.json().get("results", [])
                if not items:
                    dbg("text final lookup empty", country)
                    continue
                art = items[0].get("artworkUrl100") or items[0].get("artworkUrl60") or items[0].get("artworkUrl512")
                track_count = items[0].get("trackCount")
                if art:
                    url = upscale(art, size)
                    dbg("OK cover (text) from", country, "=>", url, "trackCount=", track_count)
                    return {"thumbnail": url, "track_count": track_count}
            except:
                continue
    return None

def get_album_cover(artist: str, album: str, size: int = DEFAULT_COVER_SIZE) -> dict | None:
    """
    Función principal para obtener el cover de un álbum.
    Primero intenta por catálogo del artista, luego por búsqueda de texto.
    Devuelve: {"thumbnail": "url", "track_count": number} o None
    """
    result = apple_cover_by_artist_catalog(artist, album, size=size)
    if not result:
        dbg("catalog flow NOT_FOUND → trying text search fallback…")
        result = apple_cover_by_text_search(artist, album, size=size)
    return result

# ============================================================================
# FUNCIONES DE YOUTUBE MUSIC (Artist ID)
# ============================================================================

def get_youtube_artist_id(artist: str) -> str | None:
    """
    Busca el artist_id (browseId) en YouTube Music.
    Devuelve el browseId o None si no encuentra.
    """
    try:
        ytmusic = YTMusic()
        results = ytmusic.search(artist, filter='artists', limit=5)
        
        if not results:
            dbg(f"YT Music: No results for {artist}")
            return None
        
        # Normalizar nombre del artista para comparar
        artist_norm = norm(artist)
        
        # Buscar match exacto o muy cercano
        for result in results:
            result_name = result.get('artist', '')
            if norm(result_name) == artist_norm:
                browse_id = result.get('browseId')
                dbg(f"YT Music: Found exact match for {artist} => {browse_id}")
                return browse_id
        
        # Si no hay match exacto, tomar el primero
        first_result = results[0]
        browse_id = first_result.get('browseId')
        dbg(f"YT Music: Using first result for {artist} => {browse_id}")
        return browse_id
        
    except Exception as e:
        dbg(f"YT Music error for {artist}: {e}")
        return None

# ============================================================================
# FUNCIÓN PRINCIPAL
# ============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Scraper de álbumes 2025 con covers de iTunes")
    parser.add_argument("--limit", type=int, default=None, 
                        help="Procesar solo los primeros N álbumes (útil para testear)")
    args = parser.parse_args()
    
    print("="*70)
    print("🎵 SCRAPER DE ÁLBUMES 2025 CON COVERS")
    print(f"⏱️  Delay: {DELAY_BETWEEN_ALBUMS}s entre álbumes")
    print("="*70)
    print()
    
    # Paso 1: Scraper de Wikipedia
    albums = scrape_wikipedia_albums()
    print(f"✅ Encontrados {len(albums)} álbumes en Wikipedia\n")
    
    # Paso 2: Filtrar solo Nov/Dec 2025 + TBA
    """ albums = filter_nov_dec_2025(albums)
    print(f"🎯 Filtrados Nov/Dec 2025 + TBA: {len(albums)} álbumes\n") """
    
    # TEST: Descomentar para probar con 1 solo álbum primero
    """ albums = albums[:1]
    print(f"⚠️  TEST MODE: Procesando solo 1 álbum\n") """ 
    
    if args.limit:
        albums = albums[:args.limit]
        print(f"⚠️  Procesando solo los primeros {len(albums)} (--limit {args.limit})\n")
    
    # Calcular tiempo estimado
    estimated_time = len(albums) * DELAY_BETWEEN_ALBUMS / 60
    print(f"⏱️  Tiempo estimado: ~{estimated_time:.1f} minutos\n")
    
    # Paso 3: Buscar covers y artist IDs
    print("🖼️  Buscando covers y artist IDs...")
    print("   (con delays de seguridad para evitar rate limits)\n")
    
    found_covers = 0
    found_artist_ids = 0
    for i, album in enumerate(albums, 1):
        print(f"[{i}/{len(albums)}] {album['artist']} - {album['album']}", end=" ", flush=True)
        
        # Buscar cover en iTunes
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
            print(f"✗ (error: {e})", end=" ", flush=True)
        
        # Buscar artist_id en YouTube Music
        try:
            artist_id = get_youtube_artist_id(album['artist'])
            if artist_id:
                album['artist_id'] = artist_id
                found_artist_ids += 1
                print("✓")
            else:
                print("✗")
        except Exception as e:
            print(f"✗")
        
        # ⚠️ DELAY LARGO entre álbumes para evitar rate limit
        if i < len(albums):
            print(f"   ⏳ Esperando {DELAY_BETWEEN_ALBUMS}s...", end="\r")
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
    
    # Mostrar resultados completos antes de guardar
    print("📋 PRIMEROS 10 RESULTADOS:\n")
    for i, album in enumerate(albums[:10], 1):
        print(f"{i}.")
        print(f"  release_date: {album['release_date']}")
        if 'artist_id' in album:
            print(f"  artist_id: {album['artist_id']}")
        print(f"  artist: {album['artist']}")
        print(f"  album: {album['album']}")
        if 'label' in album:
            print(f"  label: {album['label']}")
        if 'thumbnail' in album:
            print(f"  thumbnail: {album['thumbnail']}")
        else:
            print(f"  thumbnail: NOT_FOUND")
        if 'track_count' in album:
            print(f"  track_count: {album['track_count']}")
        print()
    
    # Guardar JSON
    import json
    """ from pathlib import Path """
    # Crear carpeta data si no existe
    """ Path('data').mkdir(exist_ok=True) """

    output_file = 'data/albums_covers.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(albums, f, indent=2, ensure_ascii=False)
        print(f"Guardado en '{output_file}'")

if __name__ == "__main__":
    main()