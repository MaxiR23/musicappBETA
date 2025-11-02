#!/usr/bin/env python3
"""
Script para scrapear upcoming albums de Wikipedia 2025
EJECUTAR EN TU MÁQUINA LOCAL, NO EN CLAUDE
"""

import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime

print("🎵 Scrapeando Wikipedia...")

url = "https://en.wikipedia.org/wiki/List_of_2025_albums"
response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(response.content, 'html.parser')

def clean_text(text):
    """Limpia referencias [1], [2], etc"""
    return re.sub(r'\[\d+\]', '', text).strip()

def parse_date_to_iso(date_str):
    """Convierte 'December12' a '2025-12-12'"""
    if not date_str or date_str == 'TBA':
        return date_str
    
    try:
        date_obj = datetime.strptime(f"{date_str} 2025", "%B%d %Y")
        return date_obj.strftime("%Y-%m-%d")
    except:
        return date_str

def parse_dated_albums(table, current_date=None):
    """Parsea álbumes con fecha definida"""
    albums = []
    
    for row in table.find_all('tr')[1:]:  # Skip header
        cols = row.find_all(['td', 'th'])
        
        if len(cols) == 0:
            continue
        
        first_text = cols[0].get_text(strip=True)
        
        # Detectar si es una fecha (contiene un mes)
        is_date = any(month in first_text for month in ['January', 'February', 'March', 'April', 
                                                          'May', 'June', 'July', 'August', 
                                                          'September', 'October', 'November', 'December'])
        
        # Si la primera celda tiene rowspan O es una fecha, es una fila con fecha
        if cols[0].has_attr('rowspan') or is_date:
            current_date = first_text
            artist = cols[1].get_text(strip=True) if len(cols) > 1 else ''
            album = cols[2].get_text(strip=True) if len(cols) > 2 else ''
            genre = cols[3].get_text(strip=True) if len(cols) > 3 else ''
            label = cols[4].get_text(strip=True) if len(cols) > 4 else ''
        else:
            # Fila sin fecha, usar la anterior
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
            
            # SOLO FORMATEAR LA FECHA AQUÍ
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
    
    for row in table.find_all('tr')[1:]:  # Skip header
        cols = row.find_all(['td', 'th'])
        
        if len(cols) < 2:
            continue
        
        # En la sección TBA la estructura es: Artist | Album | Genre | Label
        # No hay columna de fecha
        artist = cols[0].get_text(strip=True)
        album = cols[1].get_text(strip=True) if len(cols) > 1 else ''
        genre = cols[2].get_text(strip=True) if len(cols) > 2 else ''
        label = cols[3].get_text(strip=True) if len(cols) > 3 else ''
        
        if artist and album:
            artist = clean_text(artist)
            album = clean_text(album)
            genre = clean_text(genre)
            label = clean_text(label)
            
            # Validaciones básicas
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

# Procesar todas las tablas
dated_albums = []
tba_albums = []

# Buscar el h2 o h3 que dice "TBA" para saber dónde empieza esa sección
tba_started = False

for element in soup.find_all(['table', 'h2', 'h3']):
    if element.name in ['h2', 'h3']:
        heading_text = element.get_text(strip=True)
        if 'TBA' in heading_text or 'Unreleased' in heading_text:
            tba_started = True
    
    elif element.name == 'table' and 'wikitable' in element.get('class', []):
        if tba_started:
            # Tabla TBA
            tba_albums.extend(parse_tba_albums(element))
        else:
            # Tabla con fechas
            dated_albums.extend(parse_dated_albums(element))

# Combinar todos los álbumes
all_albums = dated_albums + tba_albums

# Mostrar resultados
count = 0
for album in all_albums:
    count += 1
    print(f"\n{count}.")
    print(f"  Release Date: {album['release_date']}")
    print(f"  Artist: {album['artist']}")
    print(f"  Album: {album['album']}")
    if 'genre' in album:
        print(f"  Genre: {album['genre']}")
    if 'label' in album:
        print(f"  Label: {album['label']}")

print(f"\n{'='*60}")
print(f"✅ Total: {len(all_albums)} álbumes")
print(f"   📅 Con fecha: {len(dated_albums)}")
print(f"   ❓ TBA: {len(tba_albums)}")
print(f"{'='*60}")

""" # Guardar JSON
import json
with open('albums.json', 'w', encoding='utf-8') as f:
    json.dump(all_albums, f, indent=2, ensure_ascii=False)

print(f"\n💾 Guardado en albums.json") """