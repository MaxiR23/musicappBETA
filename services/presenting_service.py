"""
Presenting service: devuelve tracks ATV de la playlist 'Presenting {artist}'.
Hace match entre el Presenting (mezcla ATV+OMV) y el Top Songs del artista (100% ATV)
para entregar solo audio puro.
"""
import re
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from services import music_client
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType
from services.artist_service import get_artist
from services.db_protocol import DBClient
from shared.clients import _ytmusic_client


# ── NORMALIZACION ────────────────────────────────────────
def _keys(title: str | None) -> tuple[str, str]:
    """Devuelve (full, core) normalizados para matchear titulos."""
    if not title:
        return "", ""
    t = unicodedata.normalize("NFKD", title.lower()).strip()
    t = re.sub(r"[\u2018\u2019\u201c\u201d\u2026]", "", t)
    t = re.sub(r"^[^-]{2,40}\s*[-\u2013]\s*", "", t)
    t = re.sub(
        r"\s*\((?:official\s+)?(?:music\s+)?"
        r"(?:video|audio|lyric|lyrics|visualizer|live|promo)[^)]*\)", "", t)
    t = re.sub(
        r"\s*\((?:remastered|mono|stereo|original|acoustic|"
        r"sped\s*up|slowed|nsfw|explicit|clean|extended|radio\s*edit)[^)]*\)", "", t)
    t = re.sub(r"\s*\([^)]*movement[^)]*\)", "", t)
    t = re.sub(r"\s+(stereo|live|remix)\s*$", "", t)
    t = re.sub(r"\s+(?:ft\.?|featuring)\s+", " feat. ", t)
    t = re.sub(r"\s*\(feat\.([^)]+)\)", r" feat.\1", t)
    t = re.sub(r"\s*\(with[^)]*\)", "", t)
    t = re.sub(r"[^\w\s.]", " ", t)
    full = re.sub(r"\s+", " ", t).strip()
    core = re.split(r"\s+(?:feat\.|remix\b)", full)[0].strip()
    return full, core


def _track_to_dto(track: dict) -> dict:
    """Mapea track de ytmusicapi al DTO standard del sistema."""
    artists_raw = track.get("artists") or []
    artists = [{"id": a.get("id"), "name": a.get("name")} for a in artists_raw]
    artist_display = ", ".join(a["name"] for a in artists if a.get("name"))
    primary_id = artists[0]["id"] if artists else None
    album = track.get("album") or {}
    thumbs = track.get("thumbnails") or []
    return {
        "id": track.get("videoId"),
        "title": track.get("title"),
        "thumbnail": thumbs[-1]["url"] if thumbs else None,
        "album_id": album.get("id"),
        "album_name": album.get("name"),
        "artist_id": primary_id,
        "artist_name": artist_display,
        "artists": artists,
        "duration": track.get("duration"),
        "duration_seconds": track.get("duration_seconds"),
    }


# ── MATCH ────────────────────────────────────────────────
def _build_match_index(top_tracks: list[dict]) -> tuple[dict, dict]:
    idx_full, idx_core = {}, {}
    for t in top_tracks:
        f, c = _keys(t.get("title"))
        if f:
            idx_full.setdefault(f, t)
        if c:
            idx_core.setdefault(c, t)
    return idx_full, idx_core


def _match_atv_tracks(
    presenting_tracks: list[dict],
    top_tracks: list[dict],
) -> tuple[list[dict], list[dict], Counter]:
    """
    3 reglas:
    1. Si el track ya es ATV, lo toma directo.
    2. Match exacto por titulo normalizado contra el top.
    3. Match por core (sin feat/remix) contra el top.
    """
    idx_full, idx_core = _build_match_index(top_tracks)
    matched, not_matched = [], []
    src_count: Counter = Counter()

    for p in presenting_tracks:
        if p.get("videoType") == "MUSIC_VIDEO_TYPE_ATV":
            matched.append(_track_to_dto(p))
            src_count["presenting_atv"] += 1
            continue
        f, c = _keys(p.get("title"))
        if f in idx_full:
            matched.append(_track_to_dto(idx_full[f]))
            src_count["matched_full"] += 1
        elif c in idx_core:
            matched.append(_track_to_dto(idx_core[c]))
            src_count["matched_core"] += 1
        else:
            not_matched.append(p)

    return matched, not_matched, src_count


# ── ORQUESTADOR ──────────────────────────────────────────
def get_presenting(db: DBClient, artist_id: str, use_cache: bool = True) -> dict:
    """
    Devuelve tracks ATV del Presenting del artista.
    Cache: PRESENTING:{artist_id} (TTL 24h).
    """
    if use_cache:
        cached = get_cached(CacheType.PRESENTING, suffix=artist_id)
        if cached:
            return cached

    try:
        # 1. Payload del artista (usa cache ARTIST, gratis si esta caliente)
        artist_payload = get_artist(db, artist_id)
        if artist_payload.get("error"):
            return {"artist_id": artist_id, "error": "artist_unavailable"}

        # 2. Sacar IDs del payload del artista
        presenting_meta = artist_payload.get("presenting") or {}
        presenting_playlist_id = presenting_meta.get("playlistId")
        songs_browse_id = presenting_meta.get("_songsBrowseId")

        if not presenting_playlist_id:
            return {"artist_id": artist_id, "error": "no_presenting"}

        # 3. Fallback: si el cache ARTIST es viejo y no trae _songsBrowseId
        if not songs_browse_id:
            artist_data = music_client.get_artist(artist_id)
            songs_browse_id = (artist_data.get("songs") or {}).get("browseId")
            if not songs_browse_id:
                return {"artist_id": artist_id, "error": "no_top_songs"}

        # 4. 2 calls en paralelo
        yt = _ytmusic_client()
        with ThreadPoolExecutor(max_workers=2) as ex:
            fut_pres = ex.submit(yt.get_playlist, presenting_playlist_id, 100)
            fut_top = ex.submit(yt.get_playlist, songs_browse_id, 100)
            presenting_tracks = fut_pres.result().get("tracks", [])
            top_tracks = fut_top.result().get("tracks", [])

        # 5. Match -> solo ATV
        matched, not_matched, src_count = _match_atv_tracks(presenting_tracks, top_tracks)

        if not matched:
            return {"artist_id": artist_id, "error": "no_atv_tracks"}

        header = artist_payload.get("header") or {}
        thumbnails = header.get("thumbnails") or []
        artist_thumb = thumbnails[-1].get("url") if thumbnails else None

        result = {
            "artist_id": artist_id,
            "artist_name": header.get("name"),
            "artist_thumb": artist_thumb,
            "playlist_id": presenting_playlist_id,
            "tracks": matched,
            "total": len(matched),
            "stats": {
                "presenting_total": len(presenting_tracks),
                "matched": len(matched),
                "not_matched": len(not_matched),
                "sources": dict(src_count),
            },
        }
        
        set_cached(CacheType.PRESENTING, result, suffix=artist_id)
        return result

    except Exception as e:
        print(f"[presenting_service][ERR] {artist_id}: {e}")
        return {"artist_id": artist_id, "error": "service_unavailable", "detail": str(e)}