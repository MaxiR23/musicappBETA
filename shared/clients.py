# shared/clients.py
"""
Clientes compartidos: InnerTube, YTMusic, yt-dlp
"""
__all__ = ["_ytm", "_ytmusic_client", "_ydl_global", "_YDL_GLOBAL"] # le avisa a Pylance que esas funciones son exportaciones públicas del módulo.
import threading
from functools import lru_cache

from innertube import InnerTube
import yt_dlp


# --- InnerTube global (WEB_REMIX) ---
_YTM_GLOBAL: InnerTube | None = None
_YTM_LOCK = threading.RLock()

def _ytm() -> InnerTube:
    global _YTM_GLOBAL
    with _YTM_LOCK:
        if _YTM_GLOBAL is None:
            _YTM_GLOBAL = InnerTube("WEB_REMIX")
        return _YTM_GLOBAL


# --- ytmusicapi global ---
_YTMUSIC_GLOBAL = None
_YTMUSIC_LOCK = threading.Lock()

def _ytmusic_client():
    global _YTMUSIC_GLOBAL
    if _YTMUSIC_GLOBAL is None:
        with _YTMUSIC_LOCK:
            if _YTMUSIC_GLOBAL is None:
                from ytmusicapi import YTMusic
                _YTMUSIC_GLOBAL = YTMusic()
    return _YTMUSIC_GLOBAL


# --- yt-dlp global ---
_YDL_GLOBAL: yt_dlp.YoutubeDL | None = None
_YDL_LOCK = threading.RLock()

@lru_cache(maxsize=4)
def _ydl_for(client: str) -> yt_dlp.YoutubeDL:
    class _SilentLogger:
        def debug(self, msg):   pass
        def info(self, msg):    pass
        def warning(self, msg): pass
        def error(self, msg):   pass

    opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "logger": _SilentLogger(),
        "skip_download": True,
        "noplaylist": True,
        "noprogress": True,
        "geo_bypass": True,
        "no_check_certificates": True,
        "no_check_formats": True,
        "lazy_playlist": True,
        "ignoreerrors": False,
        "file_access_retries": 0,
        "ignore_no_formats_error": True,
        "skip_unavailable_fragments": True,
        "extractor_args": {
            "youtube": {
                "skip": ["hls", "dash", "translated_subs"],
                "player_client": ["android_vr"],
                "include_live_dash": False,
            }
        },
        "socket_timeout": 1.5,
        "retries": 0,
        "extractor_retries": 0,
        "fragment_retries": 0,
        "sleep_requests": 0,
        "sleep_interval": 0,
        "max_sleep_interval": 0,
        "force_ipv4": True,
        "http_chunk_size": 2097152,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        },
        "cachedir": "/tmp/yt-dlp-cache",
        "concurrent_fragment_downloads": 1,
    }
    return yt_dlp.YoutubeDL(opts)


def _ydl_global() -> yt_dlp.YoutubeDL:
    global _YDL_GLOBAL
    if _YDL_GLOBAL is None:
        with _YDL_LOCK:
            if _YDL_GLOBAL is None:
                _YDL_GLOBAL = _ydl_for("android_vr")
    return _YDL_GLOBAL