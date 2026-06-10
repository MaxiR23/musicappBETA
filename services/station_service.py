# services/station_service.py
from __future__ import annotations
from datetime import date, timedelta

from services.db_protocol import DBClient
from services.cache_service import get_cached, set_cached
from services.cache_config import CacheType
from shared.clients import _ytmusic_client

SEED_LOOKBACK_WEEKS = 3
SEED_MAX = 6
SEED_MIN = 3

STATION_LIMIT = 50 # cuantos tracks pedir a la radio

# -- Pure --
def current_week_monday(d: date | None = None) -> date:
    d = d or date.today()
    return d - timedelta(days=d.weekday())

def seed_cutoff_week(d: date | None = None) -> date:
    return current_week_monday(d) - timedelta(weeks=SEED_LOOKBACK_WEEKS - 1)

def aggregate_artist_plays(rows: list[dict]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for row in rows:
        for entry in row.get("stats") or []:
            artist_id = entry.get("entity_id")
            if not artist_id:
                continue
            totals[artist_id] = totals.get(artist_id, 0) + (entry.get("play_count") or 0)
    return totals

def pick_seed_ids(totals: dict[str, int]) -> list[str]:
    if len(totals) < SEED_MIN:
        return []
    ranked = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    limit = SEED_MAX if len(ranked) >= SEED_MAX else SEED_MIN
    return [artist_id for artist_id, _ in ranked[:limit]]

def parse_length_to_seconds(length: str | None) -> int | None:
    if not length or not isinstance(length, str):
        return None
    try:
        parts = [int(p) for p in length.strip().split(":")]
    except ValueError:
        return None
    if len(parts) == 2:
        m, s = parts
        return m * 60 + s
    if len(parts) == 3:
        h, m, s = parts
        return h * 3600 + m * 60 + s
    return None

def pick_track_thumbnail(thumb) -> str | None:
    if not thumb:
        return None
    if isinstance(thumb, list):
        return thumb[-1].get("url") if thumb else None
    if isinstance(thumb, dict):
        return thumb.get("url")
    return None

def build_station_card(artist_data: dict, artist_id: str) -> dict:
    thumbnails = artist_data.get("thumbnails") or []
    thumbnail = thumbnails[-1].get("url") if thumbnails else None
    return {
        "artist_id": artist_id,
        "name": artist_data.get("name"),
        "thumbnail": thumbnail,
    }

def build_station_track(t: dict) -> dict:
    artists_list = t.get("artists") or []
    primary = artists_list[0] if artists_list else {}
    album = t.get("album") or {}
    length = t.get("length")
    return {
        "id": t.get("videoId"),
        "title": t.get("title"),
        "artist_name": ", ".join(a.get("name", "") for a in artists_list if a.get("name")),
        "artist_id": primary.get("id"),
        "artists": [{"id": a.get("id"), "name": a.get("name")} for a in artists_list],
        "album_id": album.get("id") if isinstance(album, dict) else None,
        "album_name": album.get("name") if isinstance(album, dict) else None,
        "thumbnail": pick_track_thumbnail(t.get("thumbnail")),
        "duration": length,
        "duration_seconds": parse_length_to_seconds(length),
        "year": t.get("year"),
    }

def filter_atv_tracks(tracks: list[dict]) -> list[dict]:
    return [t for t in tracks if t.get("videoType") == "MUSIC_VIDEO_TYPE_ATV"]


# -- IO --
def get_seed_artists(db: DBClient, user_id: str) -> list[str]:
    cutoff = seed_cutoff_week()
    resp = db.table("user_weekly_stats") \
        .select("stats") \
        .eq("user_id", user_id) \
        .eq("entity_type", "artist") \
        .gte("week_start", cutoff.isoformat()) \
        .execute()
    rows = (resp.data or []) if resp else []
    totals = aggregate_artist_plays(rows)
    return pick_seed_ids(totals)

def get_user_stations(db: DBClient, user_id: str) -> dict:
    """
    Lista de stations para home: una card por artista seed (top 3 o 6).
    Cacheado.
    Returns {"ok": True, "stations": [...]} or {"ok": False, "reason": "..."}
    Reasons: "no_stations_available" (no listening history), "error" (all ytmusicapi calls failed).
    """
    cached = get_cached(CacheType.USER_STATIONS, suffix=user_id)
    if cached is not None:
        return {"ok": True, "stations": cached}

    try:
        seed_ids = get_seed_artists(db, user_id)
    except Exception as e:
        print(f"[station_service][get_user_stations][ERROR] {user_id}: {e}")
        return {"ok": False, "reason": "error"}

    if not seed_ids:
        return {"ok": False, "reason": "no_stations_available"}

    try:
        yt = _ytmusic_client()
    except Exception as e:
        print(f"[station_service][get_user_stations][ERROR] ytmusic client: {e}")
        return {"ok": False, "reason": "error"}

    cards: list[dict] = []
    for artist_id in seed_ids:
        try:
            artist_data = yt.get_artist(artist_id)
            cards.append(build_station_card(artist_data, artist_id))
        except Exception as e:
            print(f"[station_service][get_user_stations][SKIP] {artist_id}: {e}")
            continue

    if not cards:
        # Seeds existed, but every ytmusicapi call failed.
        return {"ok": False, "reason": "error"}

    set_cached(CacheType.USER_STATIONS, cards, suffix=user_id)
    return {"ok": True, "stations": cards}

def get_station_tracks(artist_id: str) -> dict:
    """
    Devuelve los tracks de la station de un artista. Una sola llamada, sin sessions.
    Returns {"ok": True, "tracks": [...]} or {"ok": False, "reason": "..."}
    Reasons: "station_not_found" (artist has no radioId), "error" (ytmusicapi failure).
    """
    try:
        yt = _ytmusic_client()
        artist_data = yt.get_artist(artist_id)
        radio_id = artist_data.get("radioId")
        if not radio_id:
            return {"ok": False, "reason": "station_not_found"}

        watch = yt.get_watch_playlist(playlistId=radio_id, radio=True, limit=STATION_LIMIT)
        tracks = watch.get("tracks", [])
        return {"ok": True, "tracks": [build_station_track(t) for t in filter_atv_tracks(tracks)]}
    except Exception as e:
        print(f"[station_service][get_station_tracks][ERROR] {artist_id}: {e}")
        return {"ok": False, "reason": "error"}
