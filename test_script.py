#!/usr/bin/env python3
# TODO: agregar cuales fallaron.S
"""
Script combinado: Scrapea álbumes de Wikipedia 2026 + busca covers en iTunes

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

MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
          'July', 'August', 'September', 'October', 'November', 'December']

# ============================================================================
# FUNCIONES DE SCRAPING (Wikipedia)
# ============================================================================

def clean_text(text):
    """Limpia referencias [1], [2], etc y normaliza 'and' pegado entre artistas."""
    text = re.sub(r'\[\d+\]', '', text).strip()
    # Wikipedia pega "and" sin espacios entre artistas colaboradores.
    # Cubre todos los casos: letra/dígito + and + letra/dígito sin espacio intermedio.
    text = re.sub(r'(\w)and([A-Z])', r'\1 and \2', text)   # "MontanaandMax" / "RJD2andSup"
    text = re.sub(r'([a-z\d])and ', r'\1 and ', text)      # "Hopkinsand " (falta espacio izq)
    text = re.sub(r' and([A-Z])', r' and \1', text)        # " andDogwood" (falta espacio der)
    return text

def parse_date_to_iso(date_str):
    """Convierte 'December12' a '2026-12-12'"""
    if not date_str or date_str == 'TBA':
        return date_str
    try:
        date_obj = datetime.strptime(f"{date_str} 2026", "%B%d %Y")
        return date_obj.strftime("%Y-%m-%d")
    except:
        return date_str

def is_date_cell(text):
    """
    Determina si un texto de celda ES una fecha (ej: 'January9') y NO un
    nombre de artista/álbum que empiece con el nombre de un mes (ej: 'Mayhem').

    Reglas:
      - Debe comenzar EXACTAMENTE con uno de los 12 meses completos
      - Inmediatamente después del mes debe haber uno o más dígitos (el día)

    Ejemplos válidos  : 'January9', 'May 1', 'December31'
    Ejemplos inválidos: 'Mayhem', 'March of the Pigs', 'September Songs'
    """
    text = text.strip()
    for month in MONTHS:
        if text.startswith(month):
            remainder = text[len(month):].strip()
            if remainder.isdigit():
                return True
    return False

def parse_dated_albums(table, current_date=None):
    """Parsea álbumes con fecha definida"""
    albums = []

    for row in table.find_all('tr')[1:]:
        cols = row.find_all(['td', 'th'])

        if len(cols) == 0:
            continue

        first_text = cols[0].get_text(strip=True)
        cell_is_date = is_date_cell(first_text) or cols[0].has_attr('rowspan')

        if cell_is_date:
            current_date = first_text
            artist = cols[1].get_text(strip=True) if len(cols) > 1 else ''
            album  = cols[2].get_text(strip=True) if len(cols) > 2 else ''
            genre  = cols[3].get_text(strip=True) if len(cols) > 3 else ''
            label  = cols[4].get_text(strip=True) if len(cols) > 4 else ''
        else:
            artist = cols[0].get_text(strip=True) if len(cols) > 0 else ''
            album  = cols[1].get_text(strip=True) if len(cols) > 1 else ''
            genre  = cols[2].get_text(strip=True) if len(cols) > 2 else ''
            label  = cols[3].get_text(strip=True) if len(cols) > 3 else ''

        if artist and album:
            artist = clean_text(artist)
            album  = clean_text(album)
            genre  = clean_text(genre)
            label  = clean_text(label)

            if not current_date or current_date == 'None':
                continue
            if not is_date_cell(current_date):
                continue
            if artist in ['TBA', 'Artist', 'None', '', 'Release date']:
                continue
            if album in ['TBA', 'Album', 'None', '', 'Artist']:
                continue
            if is_date_cell(artist):
                continue

            formatted_date = parse_date_to_iso(current_date)

            album_data = {'release_date': formatted_date, 'artist': artist, 'album': album}
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
        album  = cols[1].get_text(strip=True) if len(cols) > 1 else ''
        genre  = cols[2].get_text(strip=True) if len(cols) > 2 else ''
        label  = cols[3].get_text(strip=True) if len(cols) > 3 else ''

        if artist and album:
            artist = clean_text(artist)
            album  = clean_text(album)
            genre  = clean_text(genre)
            label  = clean_text(label)

            if artist in ['Artist', 'None', '']:
                continue
            if album in ['Album', 'None', '']:
                continue

            album_data = {'release_date': 'TBA', 'artist': artist, 'album': album}
            if genre and genre != 'TBA':
                album_data['genre'] = genre
            if label and label != 'TBA':
                album_data['label'] = label

            albums.append(album_data)

    return albums

def scrape_wikipedia_albums():
    """Scrapea todos los álbumes de Wikipedia"""
    print("🎵 Scrapeando Wikipedia...")

    url = "https://en.wikipedia.org/wiki/List_of_2026_albums"
    response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(response.content, 'html.parser')

    dated_albums = []
    tba_albums   = []
    tba_started  = False

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

# ============================================================================
# FUNCIONES DE COVER (iTunes/Apple Music)
# ============================================================================

UA             = {"User-Agent": "Mozilla/5.0"}
ITUNES_SEARCH  = "https://itunes.apple.com/search"
ITUNES_LOOKUP  = "https://itunes.apple.com/lookup"
COUNTRIES      = ["ar", "mx", "us", "es", "gb", "br", "fr", "de", "it", "pt", "ca", "au"]

def dbg(*a):
    if SHOW_DEBUG:
        print("[DEBUG]", *a, file=sys.stderr, flush=True)

def norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^\w\s]", "", s)           # elimina puntuación incl. & → puede dejar doble espacio
    s = re.sub(r"\s+", " ", s).strip()      # colapsar espacios DESPUÉS de eliminar puntuación
    s = re.sub(r"\band\b", "", s)           # "X and Y" == "X & Y" (& ya fue eliminado arriba)
    s = re.sub(r"\s+", " ", s).strip()      # colapsar espacios de nuevo tras quitar "and"
    s = re.sub(r"\b(deluxe|clean|remaster(ed)?|remix(es)?|expanded|edition)\b", "", s).strip()
    return s

def upscale(url: str, size: int = 1200) -> str | None:
    if not url:
        return None
    return (url
        .replace("60x60bb",     f"{size}x{size}bb")
        .replace("100x100bb",   f"{size}x{size}bb")
        .replace("1400x1400bb", f"{size}x{size}bb"))

def split_collab_artists(artist: str) -> list[str]:
    """
    Si el nombre de artista tiene colaboradores separados por and/&/with/etc,
    devuelve lista de candidatos a probar en orden:
      1. nombre completo (siempre primero)
      2. cada parte por separado

    Ignora separadores dentro de paréntesis.
    Ej: "Euphoria Again and Dogwood Tales" →
        ["Euphoria Again and Dogwood Tales", "Euphoria Again", "Dogwood Tales"]
    Ej: "Cxmmxns (Ben Fielding and Reuben Morgan)" →
        ["Cxmmxns (Ben Fielding and Reuben Morgan)"]
    """
    candidates = [artist]
    artist_no_parens = re.sub(r'\(.*?\)', '', artist).strip()
    parts = re.split(r'\s+(?:and|&|with|feat\.?|ft\.?|vs\.?)\s+', artist_no_parens, flags=re.IGNORECASE)
    if len(parts) > 1:
        for p in parts:
            p = p.strip()
            if p and p not in candidates:
                candidates.append(p)
    return candidates

def search_artist_id(artist: str) -> tuple[str, str] | None:
    aq     = norm(artist)
    exacts = []
    with httpx.Client(headers=UA, timeout=20, follow_redirects=True) as c:
        for country in COUNTRIES:
            try:
                time.sleep(DELAY_BETWEEN_REQUESTS)
                r = c.get(ITUNES_SEARCH, params={
                    "term": artist, "entity": "musicArtist", "limit": 10, "country": country
                })
                if r.status_code == 429:
                    dbg(f"Rate limit en {country}, esperando 10s...")
                    time.sleep(10)
                    continue
                if r.status_code != 200:
                    continue
                for it in r.json().get("results", []):
                    if norm(it.get("artistName", "")) == aq:
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
                        items.sort(key=lambda x: int(x.get("artistId", 0)), reverse=True)
                        best = (items[0], country)
                        break
                except:
                    continue
            return (str(best[0]["artistId"]), best[1]) if best else None

        seen = {}
        for it, country in exacts:
            seen.setdefault(str(it.get("artistId")), (it, set()))
            seen[str(it.get("artistId"))][1].add(country)

        def albums_count(artist_id: str, pref_country: str) -> tuple[int, str, int]:
            for cc in ("us", pref_country):
                try:
                    time.sleep(DELAY_BETWEEN_REQUESTS)
                    r = c.get(ITUNES_LOOKUP, params={
                        "id": artist_id, "entity": "album", "limit": 200, "country": cc
                    })
                    if r.status_code != 200:
                        continue
                    albs = [x for x in r.json().get("results", [])
                            if x.get("wrapperType") == "collection" and x.get("collectionType") == "Album"]
                    max_cid = max([int(x.get("collectionId", 0)) for x in albs], default=0)
                    return (len(albs), cc, max_cid)
                except:
                    continue
            return (0, pref_country, 0)

        scored = []
        for aid, (it, countries) in seen.items():
            cnt, used_cc, max_cid = albums_count(aid, next(iter(countries)))
            score = (cnt, int(used_cc == "us"), max_cid)
            scored.append((score, aid, used_cc))

        scored.sort(reverse=True)
        _, aid, cc = scored[0]
        return aid, cc

def lookup_artist_albums(artist_id: str, country: str) -> list[dict]:
    with httpx.Client(headers=UA, timeout=20, follow_redirects=True) as c:
        time.sleep(DELAY_BETWEEN_REQUESTS)
        r = c.get(ITUNES_LOOKUP, params={
            "id": artist_id, "entity": "album", "limit": 200, "country": country,
        })
        r.raise_for_status()
        rows = [x for x in r.json().get("results", []) if x.get("wrapperType") == "collection"]
        dbg("albums in", country, ":", len(rows))
        return rows

def strict_pick_album(albums: list[dict], artist: str, album: str) -> dict | None:
    aq, tq = norm(artist), norm(album)
    albums = [x for x in albums if x.get("collectionType") == "Album"]
    dbg("albums after type==Album:", len(albums))
    if not albums:
        return None

    def score(x: dict):
        an = norm(x.get("artistName", ""))
        tn = norm(x.get("collectionName", ""))
        return (int(an == aq), int(tn == tq), int(tn.startswith(tq)), int(tq in tn),
                x.get("releaseDate", ""), int(x.get("collectionId", 0)))

    albums.sort(key=score, reverse=True)
    top   = albums[0]
    a_ok  = norm(top.get("artistName", "")) == aq
    t_ok  = norm(top.get("collectionName", "")) == tq
    ts_ok = norm(top.get("collectionName", "")).startswith(tq)
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
                continue
            time.sleep(DELAY_BETWEEN_REQUESTS)
            r = c.get(ITUNES_LOOKUP, params={"id": cid, "country": country})
            if r.status_code != 200:
                continue
            items = r.json().get("results", [])
            if not items:
                continue
            art = items[0].get("artworkUrl100") or items[0].get("artworkUrl60") or items[0].get("artworkUrl512")
            track_count = items[0].get("trackCount")
            if art:
                url = upscale(art, size)
                dbg("OK cover from", country, "=>", url, "trackCount=", track_count)
                return {"thumbnail": url, "track_count": track_count}
    return None

def apple_cover_by_text_search(artist: str, album: str, size: int,
                                countries: list[str] | None = None,
                                strict_artist: bool = True) -> dict | None:
    """
    strict_artist=True  → el artistName de iTunes debe matchear (nombre completo)
    strict_artist=False → solo matchea el álbum (para fallback de colabs)
    """
    aq, tq          = norm(artist), norm(album)
    search_countries = countries if countries is not None else COUNTRIES
    with httpx.Client(headers=UA, timeout=20, follow_redirects=True) as c:
        for country in search_countries:
            try:
                time.sleep(DELAY_BETWEEN_REQUESTS)
                r = c.get(ITUNES_SEARCH, params={
                    "term": f"{artist} {album}", "media": "music",
                    "entity": "album", "limit": 200, "country": country
                })
                if r.status_code == 429:
                    time.sleep(10)
                    continue
                if r.status_code != 200:
                    dbg("text search failed", country, r.status_code)
                    continue
                results = [x for x in r.json().get("results", []) if x.get("collectionType") == "Album"]
                dbg("text search albums in", country, ":", len(results))
                if not results:
                    continue

                def score(x: dict):
                    an = norm(x.get("artistName", ""))
                    tn = norm(x.get("collectionName", ""))
                    return (int(an == aq), int(tn == tq), int(tn.startswith(tq)), int(tq in tn),
                            x.get("releaseDate", ""), int(x.get("collectionId", 0)))

                results.sort(key=score, reverse=True)
                top  = results[0]
                an   = norm(top.get("artistName", ""))
                tn   = norm(top.get("collectionName", ""))
                a_ok = (an == aq) if strict_artist else True
                t_ok = tn == tq or tn.startswith(tq)
                if not (a_ok and t_ok):
                    dbg("text top rejected by strict check")
                    continue
                cid = top.get("collectionId")
                if not cid:
                    continue
                time.sleep(DELAY_BETWEEN_REQUESTS)
                r2 = c.get(ITUNES_LOOKUP, params={"id": cid, "country": country})
                if r2.status_code != 200:
                    continue
                items = r2.json().get("results", [])
                if not items:
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
    Busca cover en iTunes/Apple Music.
    - Intenta primero con el nombre completo (catalog + text search estricto)
    - Si el artista tiene colaboradores (and/&/etc) y no encontró, prueba
      cada parte con text search relajado (solo matchea el álbum)
    """
    candidates = split_collab_artists(artist)

    # Nombre completo: catalog → text search estricto
    result = apple_cover_by_artist_catalog(candidates[0], album, size=size)
    if not result:
        result = apple_cover_by_text_search(candidates[0], album, size=size, strict_artist=True)
    if result:
        return result

    # Partes del collab: solo text search, solo álbum debe matchear, pocos países
    for candidate in candidates[1:]:
        dbg(f"Collab fallback: {candidate!r}")
        result = apple_cover_by_text_search(
            candidate, album, size=size,
            countries=["us", "gb", "ar"],
            strict_artist=False
        )
        if result:
            return result

    return None

# ============================================================================
# FUNCIONES DE YOUTUBE MUSIC (Artist ID)
# ============================================================================

def get_youtube_artist_id(artist: str) -> str | None:
    """Busca el artist_id (browseId) en YouTube Music."""
    try:
        ytmusic = YTMusic()
        results = ytmusic.search(artist, filter='artists', limit=5)

        if not results:
            dbg(f"YT Music: No results for {artist}")
            return None

        artist_norm = norm(artist)

        for result in results:
            if norm(result.get('artist', '')) == artist_norm:
                browse_id = result.get('browseId')
                dbg(f"YT Music: exact match {artist} => {browse_id}")
                return browse_id

        browse_id = results[0].get('browseId')
        dbg(f"YT Music: first result {artist} => {browse_id}")
        return browse_id

    except Exception as e:
        dbg(f"YT Music error for {artist}: {e}")
        return None

# ============================================================================
# HELPERS para caché / skip
# ============================================================================

def load_existing_json(output_file: str) -> dict:
    """Carga el JSON existente e indexa por (norm_artist, norm_album)."""
    import json, os
    if not os.path.exists(output_file):
        return {}
    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        index = {}
        for entry in data:
            key = (norm(entry.get('artist', '')), norm(entry.get('album', '')))
            index[key] = entry
        return index
    except Exception as e:
        print(f"⚠️  No se pudo leer {output_file}: {e}")
        return {}

def album_already_complete(existing: dict, artist: str, album: str) -> dict | None:
    """Devuelve entry si ya tiene thumbnail Y artist_id, sino None."""
    key   = (norm(artist), norm(album))
    entry = existing.get(key)
    if entry is None:
        return None
    if bool(entry.get('thumbnail')) and bool(entry.get('artist_id')):
        return entry
    return None

# ============================================================================
# FUNCIÓN PRINCIPAL
# ============================================================================

def main():
    import argparse, json
    parser = argparse.ArgumentParser(description="Scraper de álbumes 2026 con covers de iTunes")
    parser.add_argument("--limit", type=int, default=None,
                        help="Procesar solo los primeros N álbumes (útil para testear)")
    args = parser.parse_args()

    print("=" * 70)
    print("🎵 SCRAPER DE ÁLBUMES 2026 CON COVERS")
    print(f"⏱️  Delay: {DELAY_BETWEEN_ALBUMS}s entre álbumes")
    print("=" * 70)
    print()

    output_file = 'data/albums_covers.json'

    # Cargar JSON existente para skip
    existing = load_existing_json(output_file)
    print(f"📂 JSON existente: {len(existing)} entradas cargadas\n")

    # Paso 1: Scraper de Wikipedia
    albums = scrape_wikipedia_albums()
    print(f"✅ Encontrados {len(albums)} álbumes en Wikipedia\n")

    if args.limit:
        albums = albums[:args.limit]
        print(f"⚠️  Procesando solo los primeros {len(albums)} (--limit {args.limit})\n")

    # Merge con caché: skip si ya está completo, preservar parciales
    skipped    = 0
    needs_work = []
    for album in albums:
        cached = album_already_complete(existing, album['artist'], album['album'])
        if cached:
            album.update(cached)
            skipped += 1
        else:
            key = (norm(album['artist']), norm(album.get('album', '')))
            if key in existing:
                partial = existing[key]
                for field in ('thumbnail', 'track_count', 'artist_id'):
                    if field in partial and field not in album:
                        album[field] = partial[field]
            needs_work.append(album)

    print(f"⏭️  Skipped (ya completos): {skipped}")
    print(f"🔍 A procesar: {len(needs_work)}\n")

    if needs_work:
        estimated_time = len(needs_work) * DELAY_BETWEEN_ALBUMS / 60
        print(f"⏱️  Tiempo estimado: ~{estimated_time:.1f} minutos\n")

    print("🖼️  Buscando covers y artist IDs...")
    print("   (con delays de seguridad para evitar rate limits)\n")

    found_covers     = 0
    found_artist_ids = 0

    for i, album in enumerate(needs_work, 1):
        print(f"[{i}/{len(needs_work)}] {album['artist']} - {album['album']}", end=" ", flush=True)

        # Cover iTunes
        if not album.get('thumbnail'):
            try:
                cover_data = get_album_cover(album['artist'], album['album'])
                if cover_data:
                    album['thumbnail']   = cover_data['thumbnail']
                    album['track_count'] = cover_data['track_count']
                    found_covers += 1
                    print("✓", end=" ", flush=True)
                else:
                    print("✗", end=" ", flush=True)
            except Exception as e:
                print(f"✗ (error: {e})", end=" ", flush=True)
        else:
            print("🖼️ ", end=" ", flush=True)

        # Artist ID YouTube Music
        if not album.get('artist_id'):
            try:
                artist_id = get_youtube_artist_id(album['artist'])
                if artist_id:
                    album['artist_id'] = artist_id
                    found_artist_ids += 1
                    print("✓")
                else:
                    print("✗")
            except Exception:
                print("✗")
        else:
            print("🎵")

        if i < len(needs_work):
            print(f"   ⏳ Esperando {DELAY_BETWEEN_ALBUMS}s...", end="\r")
            time.sleep(DELAY_BETWEEN_ALBUMS)

    print()
    print("=" * 70)
    print("📊 RESULTADOS:")
    print("=" * 70)
    total_with_cover  = sum(1 for a in albums if a.get('thumbnail'))
    total_with_artist = sum(1 for a in albums if a.get('artist_id'))
    print(f"Total álbumes:          {len(albums)}")
    print(f"Skipped (completos):    {skipped}")
    print(f"Procesados:             {len(needs_work)}")
    print(f"  Covers nuevos:        {found_covers}")
    print(f"  Artist IDs nuevos:    {found_artist_ids}")
    print(f"Total con cover:        {total_with_cover}")
    print(f"Total con artist ID:    {total_with_artist}")
    print(f"Sin cover:              {len(albums) - total_with_cover}")
    print(f"Sin artist ID:          {len(albums) - total_with_artist}")
    print("=" * 70)
    print()

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
        print(f"  thumbnail: {album.get('thumbnail', 'NOT_FOUND')}")
        if 'track_count' in album:
            print(f"  track_count: {album['track_count']}")
        print()

    from pathlib import Path
    Path('data').mkdir(exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(albums, f, indent=2, ensure_ascii=False)
    print(f"Guardado en '{output_file}'")

if __name__ == "__main__":
    main()