# services/music_lookup.py
from __future__ import annotations

from typing import Any, Dict, List, Optional
from functools import lru_cache
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

# ── ENV centralizado (DRY) ───────────────────────────────────────────────
@dataclass(frozen=True)
class _MusicEnv:
    seed_playlist_id: str = (os.getenv("FEED_MUSIC_RELEASE_PLAYLIST_ID") or "").strip()
    playlist_base_url: str = (os.getenv("RELEASED_PLAYLIST_BASE_URL") or "https://music.youtube.com").rstrip("/")

_ENV = _MusicEnv()

# Interno: proveedor real de metadata (no exponer su nombre afuera)
try:
    from ytmusicapi import YTMusic  # noqa: F401
except Exception as e:  # pragma: no cover
    raise RuntimeError("Provider library not available") from e


@lru_cache(maxsize=1)
def _provider() -> "YTMusic":
    # Inicializa una única instancia (tokenless funciona para búsquedas públicas)
    return YTMusic()

class MusicLookup:
    """
    Fachada genérica para búsquedas de álbumes y canciones.
    No expone detalles del proveedor subyacente.
    """
    # ── Seed playlist → pares (title, artist) ────────────────────────────
    @staticmethod
    def get_seed_pairs(playlist_id: str = None, limit: int = 500) -> list[dict[str, str]]:
        """
        Lee una playlist y devuelve [{'title': '...', 'artist': '...'}].
        """
        # Si no pasan playlist_id, usa el del ENV 
        pid = playlist_id or _ENV.seed_playlist_id
    
        if not pid:
            raise RuntimeError("Falta playlist_id o FEED_MUSIC_RELEASE_PLAYLIST_ID")

        prov = _provider()
        raw = prov.get_watch_playlist(playlistId=pid, limit=limit) or {}
        tracks = raw.get("tracks") or []

        pairs: list[dict[str, str]] = []
        for t in tracks:
            title = (t.get("title") or "").strip()
            arts  = t.get("artists") or []
            artist = ", ".join((a.get("name") or "").strip() for a in arts if isinstance(a, dict))
            if title and artist:
                pairs.append({"title": title, "artist": artist})
        return pairs

    # ── Álbumes ───────────────────────────────────────────────────────────
    @staticmethod
    def search_albums(query: str, limit: int = 1) -> List[Dict[str, Any]]:
        prov = _provider()
        return prov.search(query, filter="albums", limit=limit) or []

    @staticmethod
    def get_album(browse_id: str) -> Dict[str, Any]:
        prov = _provider()
        return prov.get_album(browse_id) or {}

    # ── Canciones ─────────────────────────────────────────────────────────
    @staticmethod
    def search_songs(query: str, limit: int = 1) -> List[Dict[str, Any]]:
        prov = _provider()
        return prov.search(query, filter="songs", limit=limit) or []

    @staticmethod
    def get_song(video_id: str) -> Dict[str, Any]:
        prov = _provider()
        return prov.get_song(video_id) or {}

    # ── Helpers de extracción segura ──────────────────────────────────────
    @staticmethod
    def first_album_id(results: List[Dict[str, Any]]) -> Optional[str]:
        if not results:
            return None
        return results[0].get("browseId")

    @staticmethod
    def first_song_id(results: List[Dict[str, Any]]) -> Optional[str]:
        if not results:
            return None
        return results[0].get("videoId")