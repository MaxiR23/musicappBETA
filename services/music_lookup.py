# services/music_lookup.py
from __future__ import annotations

from typing import Any, Dict, List, Optional
from functools import lru_cache

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

    # ── Álbumes ───────────────────────────────────────────────────────────
    @staticmethod
    def search_albums(query: str, limit: int = 1) -> List[Dict[str, Any]]:
        prov = _provider()
        # filter="albums" limita a álbumes
        return prov.search(query, filter="albums", limit=limit) or []

    @staticmethod
    def get_album(browse_id: str) -> Dict[str, Any]:
        prov = _provider()
        return prov.get_album(browse_id) or {}

    # ── Canciones ─────────────────────────────────────────────────────────
    @staticmethod
    def search_songs(query: str, limit: int = 1) -> List[Dict[str, Any]]:
        prov = _provider()
        # filter="songs" limita a canciones
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