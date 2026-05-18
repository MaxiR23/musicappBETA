"""
Popula las playlists curadas por genero desde YT Music a la base de datos.

Mejoras:
  - Cache persistente en disco (JSON) para evitar hits redundantes a YT.
  - Diferencia errores transitorios (no cachea) vs. tracks no encontrados (cachea).
  - Reporte profesional al final con resumen y detalle de fallos.
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from data.genre_playlists import GENRE_PLAYLISTS
from shared.clients import _ytmusic_client
from services.supabase_service import supabase_service as sb
from services.genre_repo import (
    upsert_genre,
    upsert_genre_playlist,
    insert_genre_playlist_tracks,
)
from utils.feed_utils import map_track, _with_retry


# ---------------------------------------------------------------------------
# Cache persistente
# ---------------------------------------------------------------------------

# Sentinel para diferenciar "track no encontrado" de "nunca buscado".
_NOT_FOUND_SENTINEL = "__NOT_FOUND__"

DEFAULT_CACHE_PATH = Path(__file__).resolve().parent / ".genre_track_cache.json"


class PersistentTrackCache:
    """
    Cache en disco (JSON) para resultados de map_track.

    Formato interno:
        {
            "artist_lower|||title_lower": { ...track dict... }   # encontrado
            "artist_lower|||title_lower": "__NOT_FOUND__"        # buscado, no existe
        }

    Los errores transitorios NO se guardan: la proxima corrida reintenta.
    """

    def __init__(self, path: Path | str = DEFAULT_CACHE_PATH):
        self._path = Path(path)
        self._data: Dict[str, Any] = {}
        self._dirty = False
        self._load()

    # -- persistencia -------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            self._data = {}
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            print(f"Cache cargado: {len(self._data)} entradas desde {self._path}")
        except (json.JSONDecodeError, OSError) as exc:
            print(f"WARN: No se pudo leer cache ({exc}), se inicia vacio.")
            self._data = {}

    def save(self) -> None:
        """Guarda a disco solo si hubo cambios."""
        if not self._dirty:
            return
        tmp = self._path.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False)
            tmp.replace(self._path)
            self._dirty = False
        except OSError as exc:
            print(f"WARN: No se pudo guardar cache: {exc}")

    # -- API publica --------------------------------------------------------

    @staticmethod
    def _key(artist: str, title: str) -> str:
        return f"{artist.strip().lower()}|||{title.strip().lower()}"

    def contains(self, artist: str, title: str) -> bool:
        return self._key(artist, title) in self._data

    def get(self, artist: str, title: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Retorna (found_in_cache, track_or_none).
        Si no esta en cache: (False, None).
        Si esta como NOT_FOUND: (True, None).
        Si esta con datos: (True, track_dict).
        """
        key = self._key(artist, title)
        if key not in self._data:
            return False, None
        val = self._data[key]
        if val == _NOT_FOUND_SENTINEL:
            return True, None
        return True, val

    def put(self, artist: str, title: str, track: Optional[Dict[str, Any]]) -> None:
        key = self._key(artist, title)
        self._data[key] = track if track is not None else _NOT_FOUND_SENTINEL
        self._dirty = True

    def __len__(self) -> int:
        return len(self._data)

    @property
    def found_count(self) -> int:
        return sum(1 for v in self._data.values() if v != _NOT_FOUND_SENTINEL)

    @property
    def not_found_count(self) -> int:
        return sum(1 for v in self._data.values() if v == _NOT_FOUND_SENTINEL)


# Instancia global; se inicializa en main().
_cache: PersistentTrackCache


# ---------------------------------------------------------------------------
# Tracker de resultados (para el reporte final)
# ---------------------------------------------------------------------------

@dataclass
class PlaylistResult:
    genre: str
    playlist_title: str
    playlist_id: str
    tracks_in_source: int = 0
    tracks_mapped: int = 0
    cache_hits: int = 0
    errors_transient: int = 0
    tracks_not_found: int = 0
    inserted_in_db: int = 0
    skipped_duplicate: int = 0
    status: str = "OK"
    error_detail: str = ""


@dataclass
class RunTracker:
    results: List[PlaylistResult] = field(default_factory=list)
    failed_mappings: List[Dict[str, str]] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)

    def add(self, result: PlaylistResult) -> None:
        self.results.append(result)

    def log_failed_mapping(self, genre: str, playlist: str, artist: str, title: str, reason: str) -> None:
        self.failed_mappings.append({
            "genre": genre,
            "playlist": playlist,
            "artist": artist,
            "title": title,
            "reason": reason,
        })

    def print_report(self) -> None:
        elapsed = time.time() - self.start_time
        mins, secs = divmod(int(elapsed), 60)
        hours, mins = divmod(mins, 60)

        print()
        print("=" * 80)
        print("  REPORTE FINAL")
        print("=" * 80)
        print(f"  Duracion total: {hours:02d}h {mins:02d}m {secs:02d}s")
        print(f"  Cache persistente: {len(_cache)} entradas ({_cache.found_count} encontrados, {_cache.not_found_count} no encontrados)")
        print()

        if not self.results:
            print("  No se proceso ninguna playlist.")
            print("=" * 80)
            return

        # -- Tabla resumen por playlist --
        header = f"  {'Genero':<20} {'Playlist':<30} {'Fuente':>7} {'Mapeados':>9} {'Cache':>6} {'Errs':>5} {'DB':>5} {'Estado':<8}"
        print(header)
        print("  " + "-" * (len(header) - 2))

        total_source = 0
        total_mapped = 0
        total_cache = 0
        total_errors = 0
        total_db = 0
        ok_count = 0

        for r in self.results:
            total_source += r.tracks_in_source
            total_mapped += r.tracks_mapped
            total_cache += r.cache_hits
            total_errors += r.errors_transient
            total_db += r.inserted_in_db

            status_tag = r.status
            if r.status == "OK":
                ok_count += 1

            genre_short = (r.genre[:18] + "..") if len(r.genre) > 20 else r.genre
            pl_short = (r.playlist_title[:28] + "..") if len(r.playlist_title) > 30 else r.playlist_title

            print(f"  {genre_short:<20} {pl_short:<30} {r.tracks_in_source:>7} {r.tracks_mapped:>9} {r.cache_hits:>6} {r.errors_transient:>5} {r.inserted_in_db:>5} {status_tag:<8}")

        print("  " + "-" * (len(header) - 2))
        print(f"  {'TOTAL':<20} {'':<30} {total_source:>7} {total_mapped:>9} {total_cache:>6} {total_errors:>5} {total_db:>5} {ok_count}/{len(self.results)} OK")
        print()

        # -- Playlists con error --
        failed_playlists = [r for r in self.results if r.status != "OK"]
        if failed_playlists:
            print("  PLAYLISTS CON PROBLEMAS:")
            print("  " + "-" * 70)
            for r in failed_playlists:
                print(f"    [{r.status}] {r.genre} / {r.playlist_title}")
                if r.error_detail:
                    print(f"           Detalle: {r.error_detail}")
            print()

        # -- Top fallos de mapeo (maximo 30) --
        if self.failed_mappings:
            show = self.failed_mappings[:30]
            remaining = len(self.failed_mappings) - len(show)
            print(f"  TRACKS NO MAPEADOS (mostrando {len(show)} de {len(self.failed_mappings)}):")
            print("  " + "-" * 70)
            for fm in show:
                print(f"    {fm['artist']} - {fm['title']}")
                print(f"      Playlist: {fm['playlist']} | Razon: {fm['reason']}")
            if remaining > 0:
                print(f"    ... y {remaining} mas.")
            print()

        # -- Resumen ejecutivo --
        pct_mapped = (total_mapped / total_source * 100) if total_source else 0
        pct_cache = (total_cache / (total_mapped + total_errors + len([r for r in self.results if r.tracks_not_found > 0])) * 100) if (total_mapped + total_errors) else 0

        print("  RESUMEN:")
        print(f"    Playlists procesadas: {len(self.results)} ({ok_count} exitosas, {len(self.results) - ok_count} con problemas)")
        print(f"    Tracks totales en fuente: {total_source}")
        print(f"    Tracks mapeados: {total_mapped} ({pct_mapped:.1f}%)")
        print(f"    Cache hits: {total_cache}")
        print(f"    Errores transitorios: {total_errors}")
        print(f"    Tracks insertados en DB: {total_db}")
        print("=" * 80)


# Instancia global del tracker.
_tracker = RunTracker()


# ---------------------------------------------------------------------------
# Logica de procesamiento
# ---------------------------------------------------------------------------

def process_playlist(
    genre_name: str,
    playlist_id: str,
    playlist_title: str,
    limit: int = 100,
    micro_pause: float = 0.3,
) -> Tuple[List[Dict[str, Any]], PlaylistResult]:
    """Extrae y mapea tracks de una playlist de YT Music."""

    result = PlaylistResult(
        genre=genre_name,
        playlist_title=playlist_title,
        playlist_id=playlist_id,
    )

    # -- Paso 1: Extraer tracks crudos de YT Music --------------------------
    print(f"  Extrayendo '{playlist_title}'...")

    try:
        raw = _with_retry(
            _ytmusic_client().get_watch_playlist,
            playlistId=playlist_id,
            limit=limit,
        ) or {}
        tracks_raw = raw.get("tracks") or []
    except Exception as exc:
        result.status = "ERROR_EXTRACT"
        result.error_detail = str(exc)
        print(f"  Error extrayendo playlist: {exc}")
        return [], result

    pairs: List[Dict[str, str]] = []
    for t in tracks_raw:
        title = (t.get("title") or "").strip()
        artists = t.get("artists") or []
        artist = ", ".join(
            a.get("name", "").strip()
            for a in artists
            if isinstance(a, dict)
        )
        if title and artist:
            pairs.append({"title": title, "artist": artist})

    result.tracks_in_source = len(pairs)
    print(f"  {len(pairs)} tracks encontrados en fuente")

    if not pairs:
        result.status = "EMPTY"
        return [], result

    # -- Paso 2: Mapear cada track (con cache persistente) ------------------
    mapped_tracks: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    save_interval = 25  # guardar cache cada N tracks nuevos mapeados
    new_since_save = 0

    for i, pair in enumerate(pairs, 1):
        artist = pair["artist"]
        title = pair["title"]

        # Consultar cache persistente
        in_cache, cached_track = _cache.get(artist, title)

        if in_cache:
            result.cache_hits += 1
            if cached_track and (tid := cached_track.get("id")) and tid not in seen_ids:
                mapped_tracks.append(cached_track)
                seen_ids.add(tid)
            elif not cached_track:
                result.tracks_not_found += 1
            continue

        # No esta en cache: pegar a YT / Spotify via map_track
        try:
            track = map_track(artist, title)
        except Exception as exc:
            # Error transitorio: NO cacheamos para reintentar luego.
            result.errors_transient += 1
            _tracker.log_failed_mapping(genre_name, playlist_title, artist, title, f"Excepcion: {exc}")
            print(f"  Error transitorio mapeando '{artist} - {title}': {exc}")
            continue

        # Guardar en cache persistente (incluso None = no encontrado)
        _cache.put(artist, title, track)
        new_since_save += 1

        if track and (tid := track.get("id")) and tid not in seen_ids:
            mapped_tracks.append(track)
            seen_ids.add(tid)
        elif track and (tid := track.get("id")) and tid in seen_ids:
            result.skipped_duplicate += 1
        elif not track:
            result.tracks_not_found += 1
            _tracker.log_failed_mapping(genre_name, playlist_title, artist, title, "No encontrado en map_track")

        # Flush cache periodicamente
        if new_since_save >= save_interval:
            _cache.save()
            new_since_save = 0

        # Progreso
        if i % 10 == 0:
            print(f"  Mapeados {len(mapped_tracks)}/{len(pairs)} (cache: {result.cache_hits}, errores: {result.errors_transient})")

        # Micro-pausa solo cuando pegamos a la API (no cache hit)
        if micro_pause and i % 3 == 0:
            time.sleep(micro_pause)

    # Flush final de esta playlist
    _cache.save()

    result.tracks_mapped = len(mapped_tracks)
    print(f"  {len(mapped_tracks)} tracks mapeados ({result.cache_hits} cache hits, {result.errors_transient} errores, {result.tracks_not_found} no encontrados)")
    return mapped_tracks, result


def populate_genre_entry(
    entry: Dict[str, Any],
    limit_per_playlist: int = 100,
    wait_between_playlists: int = 10,
) -> None:
    """Procesa un genero completo con todas sus playlists."""

    genre_name = entry.get("genre", "???")
    genre_slug = entry.get("slug")
    sort_order = entry.get("sort_order", 0)
    category = entry.get("category")
    playlists = entry.get("playlists", [])

    category_str = f" [{category}]" if category else ""
    print(f"\n{'=' * 70}")
    print(f"Genero: {genre_name}{category_str}")
    print(f"{'=' * 70}")

    try:
        genre_id = upsert_genre(
            db=sb,
            name=genre_name,
            slug=genre_slug,
            sort_order=sort_order,
        )
        print(f"Genero '{genre_name}' -> {genre_id}")
    except Exception as exc:
        print(f"Error insertando genero: {exc}")
        # Registrar todas las playlists como fallidas
        for pd in playlists:
            pr = PlaylistResult(
                genre=genre_name,
                playlist_title=pd.get("title", "???"),
                playlist_id=pd.get("id", "???"),
                status="ERROR_GENRE",
                error_detail=str(exc),
            )
            _tracker.add(pr)
        return

    total_playlists = len(playlists)

    for idx, playlist_data in enumerate(playlists, 1):
        playlist_title = playlist_data.get("title", "???")
        playlist_id = playlist_data.get("id", "???")

        print(f"\n  [{idx}/{total_playlists}] {playlist_title}")
        print(f"  ID: {playlist_id}")

        tracks, pl_result = process_playlist(
            genre_name=genre_name,
            playlist_id=playlist_id,
            playlist_title=playlist_title,
            limit=limit_per_playlist,
        )

        if not tracks:
            if pl_result.status == "OK":
                pl_result.status = "NO_TRACKS"
            _tracker.add(pl_result)
            print(f"  No se obtuvieron tracks, saltando...")
            continue

        try:
            db_playlist_id = upsert_genre_playlist(
                db=sb,
                genre_id=genre_id,
                title=playlist_title,
                category=category,
                sort_order=idx,
            )
            print(f"  Playlist creada/actualizada -> {db_playlist_id}")
        except Exception as exc:
            pl_result.status = "ERROR_DB_PL"
            pl_result.error_detail = str(exc)
            _tracker.add(pl_result)
            print(f"  Error creando playlist en DB: {exc}")
            continue

        try:
            inserted = insert_genre_playlist_tracks(db=sb, playlist_id=db_playlist_id, tracks=tracks)
            pl_result.inserted_in_db = inserted
            print(f"  {inserted} tracks insertados en DB")
        except Exception as exc:
            pl_result.status = "ERROR_DB_TRACKS"
            pl_result.error_detail = str(exc)
            _tracker.add(pl_result)
            print(f"  Error insertando tracks: {exc}")
            continue

        _tracker.add(pl_result)

        if idx < total_playlists:
            print(f"  Esperando {wait_between_playlists}s antes de la proxima playlist...")
            time.sleep(wait_between_playlists)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    global _cache, _tracker

    parser = argparse.ArgumentParser(
        description="Popula playlists curadas por genero desde YT Music",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximo de tracks por playlist (default: 100)",
    )
    parser.add_argument(
        "--genre",
        type=str,
        default=None,
        help='Procesar solo un genero especifico (ej: "Hip Hop")',
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=10,
        help="Segundos de espera entre playlists (default: 10)",
    )
    parser.add_argument(
        "--cache-file",
        type=str,
        default=None,
        help="Ruta al archivo de cache (default: .genre_track_cache.json junto al script)",
    )
    parser.add_argument(
        "--reset-cache",
        action="store_true",
        help="Borrar el cache persistente antes de empezar",
    )

    args = parser.parse_args(argv)

    # -- Inicializar cache persistente --
    cache_path = Path(args.cache_file) if args.cache_file else DEFAULT_CACHE_PATH

    if args.reset_cache and cache_path.exists():
        cache_path.unlink()
        print(f"Cache eliminado: {cache_path}")

    _cache = PersistentTrackCache(path=cache_path)

    # Registrar guardado al salir (por si hay un crash o Ctrl+C no manejado).
    atexit.register(_cache.save)

    # -- Inicializar tracker --
    _tracker = RunTracker()

    # -- Configuracion --
    print("=" * 70)
    print("  POPULATE GENRE PLAYLISTS")
    print("=" * 70)
    print(f"  Config:")
    print(f"    Limit por playlist:  {args.limit} tracks")
    print(f"    Wait entre playlists: {args.wait}s")
    print(f"    Cache:               {cache_path} ({len(_cache)} entradas)")
    if args.genre:
        print(f"    Filtro genero:       {args.genre}")
    print()

    # -- Filtrar entradas --
    entries_to_process = GENRE_PLAYLISTS

    if args.genre:
        entries_to_process = [
            e for e in GENRE_PLAYLISTS
            if e.get("genre", "").lower() == args.genre.lower()
        ]
        if not entries_to_process:
            print(f"No se encontro el genero '{args.genre}'")
            return 1

    print(f"  Total de entradas a procesar: {len(entries_to_process)}")

    # -- Procesar --
    for entry in entries_to_process:
        try:
            populate_genre_entry(
                entry=entry,
                limit_per_playlist=args.limit,
                wait_between_playlists=args.wait,
            )
        except KeyboardInterrupt:
            print("\n\n  Interrupcion por usuario. Guardando cache y mostrando reporte...")
            _cache.save()
            _tracker.print_report()
            return 130
        except Exception as exc:
            print(f"\n  Error inesperado procesando entrada: {exc}")
            continue

    # -- Guardado final y reporte --
    _cache.save()
    _tracker.print_report()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())