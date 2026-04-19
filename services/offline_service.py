"""
Lógica de negocio para sincronización offline.
Funciones puras para validación, orquestación para fetch de audio.
"""
import os
import tempfile

import yt_dlp

OFFLINE_USERS = set(os.getenv("OFFLINE_USERS", "").split(",")) - {""}
COOKIES_DIR = os.getenv("OFFLINE_COOKIES_DIR", "/etc/beatly/cookies")
ALLOWED_ITAGS = {141, 774, 140, 251}

# ── Helpers ──────────────────────────────────────────────
def is_allowed(user_id: str) -> bool:
    return user_id in OFFLINE_USERS

def is_valid_itag(itag: int) -> bool:
    return itag in ALLOWED_ITAGS

def extension_for_itag(itag: int) -> str:
    return "m4a" if itag in (141, 140) else "opus"

def media_type_for_itag(itag: int) -> str:
    return "audio/mp4" if itag in (141, 140) else "audio/ogg"

def get_cookie_path(user_id: str) -> str:
    return os.path.join(COOKIES_DIR, f"{user_id}.txt")

def has_cookies(user_id: str) -> bool:
    return os.path.isfile(get_cookie_path(user_id))

def build_error(reason: str, detail: str = "") -> dict:
    return {"error": reason, "detail": detail}

def _build_client(cookie_path: str, output_path: str, itag: int) -> yt_dlp.YoutubeDL:
    """Cliente de extracción configurado para descarga con cookies."""
    class _SilentLogger:
        def debug(self, msg):   pass
        def info(self, msg):    pass
        def warning(self, msg): pass
        def error(self, msg):   pass

    return yt_dlp.YoutubeDL({
        "format": str(itag),
        "outtmpl": output_path,
        "quiet": True,
        "no_warnings": True,
        "logger": _SilentLogger(),
        "noplaylist": True,
        "noprogress": True,
        "cookiefile": cookie_path,
        "geo_bypass": True,
        "no_check_certificates": True,
        "socket_timeout": 30,
        "retries": 2,
        "extractor_retries": 1,
        "force_ipv4": True,
        "js_runtimes": {"deno": {}},
        "extractor_args": {
            "youtube": {
                "player_client": ["web_music"],
                "player_skip": ["webpage", "configs"],
                "skip": ["hls", "dash", "translated_subs"],
            }
        },
    })

# ── IO ───────────────────────────────────────────────────
def fetch_audio(track_id: str, user_id: str, itag: int) -> dict:
    if not is_allowed(user_id):
        return build_error("not_found", "user not in allowlist")

    if not is_valid_itag(itag):
        return build_error("invalid_itag", f"itag {itag} is not supported")

    if not has_cookies(user_id):
        path = get_cookie_path(user_id)
        return build_error("no_cookies", f"cookie file not found at {path}")

    cookie_path = get_cookie_path(user_id)
    ext = extension_for_itag(itag)
    url = f"https://music.youtube.com/watch?v={track_id}"

    try:
        tmp_dir = tempfile.mkdtemp(prefix="offline_")
        output_path = os.path.join(tmp_dir, f"{track_id}.{ext}")

        client = _build_client(cookie_path, output_path, itag)
        client.download([url])

        if not os.path.isfile(output_path):
            print(f"[offline_service][WARN] {track_id}: archivo no generado")
            return build_error("fetch_failed", f"output file not created for {track_id}")

        return {"path": output_path, "track_id": track_id}

    except yt_dlp.utils.DownloadError as e:
        print(f"[offline_service][ERR] {track_id}: {e}")
        return build_error("fetch_failed", str(e)[:200])
    except Exception as e:
        print(f"[offline_service][ERR] {track_id}: {e}")
        return build_error("service_unavailable", str(e)[:200])