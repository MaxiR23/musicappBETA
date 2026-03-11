"""
Popula las playlists curadas por género desde YT Music a la base de datos.
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Any, Dict, List, Optional

from data.genre_playlists import GENRE_PLAYLISTS
from shared.clients import _ytmusic_client
from services.supabase_service import supabase_service as sb
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
    print(f"Extrayendo '{playlist_title}'...")
    
    try:
        raw = _ytmusic_client().get_watch_playlist(playlistId=playlist_id, limit=limit) or {}
        tracks = raw.get("tracks") or []
        pairs = []
        for t in tracks:
            title = (t.get("title") or "").strip()
            artists = t.get("artists") or []
            artist = ", ".join(a.get("name", "").strip() for a in artists if isinstance(a, dict))
            if title and artist:
                pairs.append({"title": title, "artist": artist})
    except Exception as e:
        print(f"Error extrayendo playlist: {e}")
        return []
    
    print(f"{len(pairs)} tracks encontrados en playlist")
    
    if not pairs:
        return []
    
    mapped_tracks: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    
    for i, pair in enumerate(pairs, 1):
        artist = pair.get("artist", "").strip()
        title = pair.get("title", "").strip()
        
        if not artist or not title:
            continue
        
        try:
            track = map_track(artist, title)
            
            if track and (track_id := track.get("id")) and track_id not in seen_ids:
                mapped_tracks.append(track)
                seen_ids.add(track_id)
                
                if i % 10 == 0:
                    print(f"Mapeados {len(mapped_tracks)}/{len(pairs)} tracks...")
            
        except Exception as e:
            print(f"Error mapeando '{artist} - {title}': {e}")
            continue
        
        if micro_pause and i % 3 == 0:
            time.sleep(micro_pause)
    
    print(f"{len(mapped_tracks)} tracks mapeados correctamente")
    return mapped_tracks

def populate_genre_entry(
    entry: Dict[str, Any],
    limit_per_playlist: int = 100,
    wait_between_playlists: int = 10,
) -> None:
    genre_name = entry.get("genre")
    genre_slug = entry.get("slug")
    sort_order = entry.get("sort_order", 0)
    category = entry.get("category")
    playlists = entry.get("playlists", [])
    
    category_str = f" [{category}]" if category else ""
    print(f"\n{'=' * 70}")
    print(f"Género: {genre_name}{category_str}")
    print(f"{'=' * 70}")
    
    try:
        genre_id = upsert_genre(
            db=sb,
            name=genre_name,
            slug=genre_slug,
            sort_order=sort_order,
        )
        print(f"Género '{genre_name}' → {genre_id}")
    except Exception as e:
        print(f"Error insertando género: {e}")
        return
    
    total_playlists = len(playlists)
    
    for idx, playlist_data in enumerate(playlists, 1):
        playlist_title = playlist_data.get("title")
        playlist_id = playlist_data.get("id")
        
        print(f"\n[{idx}/{total_playlists}] {playlist_title}")
        print(f"ID: {playlist_id}")
        
        tracks = process_playlist(
            playlist_id=playlist_id,
            playlist_title=playlist_title,
            limit=limit_per_playlist,
        )
        
        if not tracks:
            print(f"No se obtuvieron tracks, saltando...")
            continue
        
        try:
            db_playlist_id = upsert_genre_playlist(
                db=sb,
                genre_id=genre_id,
                title=playlist_title,
                category=category,
                sort_order=idx,
            )
            print(f"Playlist creada/actualizada → {db_playlist_id}")
        except Exception as e:
            print(f"Error creando playlist en DB: {e}")
            continue
        
        try:
            inserted = insert_genre_playlist_tracks(db=sb, playlist_id=db_playlist_id, tracks=tracks)
            print(f"{inserted} tracks insertados en DB")
        except Exception as e:
            print(f"Error insertando tracks: {e}")
            continue
        
        if idx < total_playlists:
            print(f"Esperando {wait_between_playlists}s antes de la próxima playlist...")
            time.sleep(wait_between_playlists)


def main(argv: Optional[List[str]] = None) -> int:
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