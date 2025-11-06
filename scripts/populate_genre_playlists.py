# scripts/populate_genre_playlists.py
"""
Popula las playlists curadas por género desde YT Music a la base de datos.
Este script:
1. Lee la estructura de data/genre_playlists.py
2. Extrae tracks de cada playlist usando YT Music
3. Mapea cada track a su versión ATV limpia
4. Persiste en la DB: genres → genre_playlists → tracks → genre_playlist_tracks

Uso:
    python -m scripts.populate_genre_playlists
    python -m scripts.populate_genre_playlists --limit 50  # Limita tracks por playlist
    python -m scripts.populate_genre_playlists --genre "Hip Hop"  # Solo un género
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Any, Dict, List, Optional

from data.genre_playlists import GENRE_PLAYLISTS
from services.music_lookup import MusicLookup
from services.genre_repo import (
    upsert_genre,
    upsert_genre_playlist,
    insert_genre_playlist_tracks,
)
from utils.feed_utils import map_track


def process_playlist(
    playlist_id: str,
    playlist_title: str,
    limit: int = 100,
    micro_pause: float = 0.3,
) -> List[Dict[str, Any]]:
    """
    Extrae y mapea tracks de una playlist.
    
    Args:
        playlist_id: ID de la playlist de YT Music
        playlist_title: Título de la playlist (para logs)
        limit: Máximo de tracks a extraer
        micro_pause: Pausa entre llamadas a map_track
    
    Returns:
        Lista de tracks mapeados (versión ATV limpia)
    """
    print(f"Extrayendo '{playlist_title}'...")
    
    # 1. Extraer pares (artist, title) de la playlist
    try:
        pairs = MusicLookup.get_seed_pairs(playlist_id=playlist_id, limit=limit)
    except Exception as e:
        print(f"Error extrayendo playlist: {e}")
        return []
    
    print(f"{len(pairs)} tracks encontrados en playlist")
    
    if not pairs:
        return []
    
    # 2. Mapear cada track a versión ATV limpia
    mapped_tracks: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    
    for i, pair in enumerate(pairs, 1):
        artist = pair.get("artist", "").strip()
        title = pair.get("title", "").strip()
        
        if not artist or not title:
            continue
        
        try:
            # map_track busca la versión ATV limpia
            track = map_track(artist, title)
            
            if track and (track_id := track.get("id")) and track_id not in seen_ids:
                mapped_tracks.append(track)
                seen_ids.add(track_id)
                
                if i % 10 == 0:
                    print(f"Mapeados {len(mapped_tracks)}/{len(pairs)} tracks...")
            
        except Exception as e:
            print(f"Error mapeando '{artist} - {title}': {e}")
            continue
        
        # Micro pausa cada 3 tracks
        if micro_pause and i % 3 == 0:
            time.sleep(micro_pause)
    
    print(f"{len(mapped_tracks)} tracks mapeados correctamente")
    return mapped_tracks


def populate_genre_entry(
    entry: Dict[str, Any],
    limit_per_playlist: int = 100,
    wait_between_playlists: int = 10,
) -> None:
    """
    Procesa una entrada completa de género (puede tener múltiples playlists).
    
    Args:
        entry: Entrada de GENRE_PLAYLISTS
        limit_per_playlist: Máximo de tracks por playlist
        wait_between_playlists: Segundos de espera entre playlists
    """
    genre_name = entry.get("genre")
    genre_slug = entry.get("slug")
    sort_order = entry.get("sort_order", 0)
    category = entry.get("category")
    playlists = entry.get("playlists", [])
    
    category_str = f" [{category}]" if category else ""
    print(f"\n{'=' * 70}")
    print(f"Género: {genre_name}{category_str}")
    print(f"{'=' * 70}")
    
    # 1. Upsert género
    try:
        genre_id = upsert_genre(
            name=genre_name,
            slug=genre_slug,
            sort_order=sort_order,
        )
        print(f"Género '{genre_name}' → {genre_id}")
    except Exception as e:
        print(f"Error insertando género: {e}")
        return
    
    # 2. Procesar cada playlist
    total_playlists = len(playlists)
    
    for idx, playlist_data in enumerate(playlists, 1):
        playlist_title = playlist_data.get("title")
        playlist_id = playlist_data.get("id")
        
        print(f"\n📀 [{idx}/{total_playlists}] {playlist_title}")
        print(f"ID: {playlist_id}")
        
        # 2.1 Extraer y mapear tracks
        tracks = process_playlist(
            playlist_id=playlist_id,
            playlist_title=playlist_title,
            limit=limit_per_playlist,
        )
        
        if not tracks:
            print(f"No se obtuvieron tracks, saltando...")
            continue
        
        # 2.2 Upsert playlist en DB
        try:
            db_playlist_id = upsert_genre_playlist(
                genre_id=genre_id,
                title=playlist_title,
                category=category,
                sort_order=idx,
            )
            print(f"Playlist creada/actualizada → {db_playlist_id}")
        except Exception as e:
            print(f"Error creando playlist en DB: {e}")
            continue
        
        # 2.3 Insertar tracks en DB
        try:
            inserted = insert_genre_playlist_tracks(db_playlist_id, tracks)
            print(f"{inserted} tracks insertados en DB")
        except Exception as e:
            print(f"Error insertando tracks: {e}")
            continue
        
        # 2.4 Rate limiting: esperar entre playlists
        if idx < total_playlists:
            print(f"Esperando {wait_between_playlists}s antes de la próxima playlist...")
            time.sleep(wait_between_playlists)


def main(argv: Optional[List[str]] = None) -> int:
    """
    Punto de entrada principal del script.
    """
    parser = argparse.ArgumentParser(
        description="Popula playlists curadas por género desde YT Music"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Máximo de tracks por playlist (default: 100)",
    )
    parser.add_argument(
        "--genre",
        type=str,
        default=None,
        help='Procesar solo un género específico (ej: "Hip Hop")',
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=10,
        help="Segundos de espera entre playlists (default: 10)",
    )
    
    args = parser.parse_args(argv)
    
    print("=" * 70)
    print("POPULATE GENRE PLAYLISTS")
    print("=" * 70)
    print(f"Config:")
    print(f" - Limit por playlist: {args.limit} tracks")
    print(f" - Wait entre playlists: {args.wait}s")
    if args.genre:
        print(f" - Filtro género: {args.genre}")
    print()
    
    # Filtrar entries si se especificó un género
    entries_to_process = GENRE_PLAYLISTS
    
    if args.genre:
        entries_to_process = [
            e for e in GENRE_PLAYLISTS 
            if e.get("genre", "").lower() == args.genre.lower()
        ]
        
        if not entries_to_process:
            print(f"No se encontró el género '{args.genre}'")
            return 1
    
    print(f"Total de entradas a procesar: {len(entries_to_process)}")
    
    # Procesar cada entrada
    for entry in entries_to_process:
        try:
            populate_genre_entry(
                entry=entry,
                limit_per_playlist=args.limit,
                wait_between_playlists=args.wait,
            )
        except KeyboardInterrupt:
            print("\n\n Interrupción por usuario. Saliendo...")
            return 130
        except Exception as e:
            print(f"\n Error procesando entrada: {e}")
            continue
    
    print("\n" + "=" * 70)
    print("PROCESO COMPLETADO")
    print("=" * 70)
    
    return 0

if __name__ == "__main__":
    raise SystemExit(main())