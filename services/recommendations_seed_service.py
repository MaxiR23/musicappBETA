from __future__ import annotations

from shared.clients import _ytm
from services import music_client
from services.db_protocol import DBClient
from services.cache_service import get_cached_legacy, set_cached_legacy
from services.activity_repo import recent_seeds_from_activity
from utils.artist_parser import parse_related_artists, pick_related_artists_section

_RECO_TTL = 20 * 60

def _extract_header_info(resp: dict) -> dict:
    header = resp.get("header", {}).get("musicImmersiveHeaderRenderer", {})
    runs = (header.get("title", {}) or {}).get("runs", []) or [{}]
    name = runs[0].get("text")
    thumbs = (
        header.get("thumbnail", {})
        .get("musicThumbnailRenderer", {})
        .get("thumbnail", {})
        .get("thumbnails", []) or []
    )
    thumb = (thumbs[-1] or {}).get("url") if thumbs else None
    return {"name": name, "thumb": thumb}


def _extract_contents(resp: dict) -> list:
    try:
        return (
            resp.get("contents", {})
            .get("singleColumnBrowseResultsRenderer", {})
            .get("tabs", [])[0]
            .get("tabRenderer", {})
            .get("content", {})
            .get("sectionListRenderer", {})
            .get("contents", [])
        )
    except (IndexError, KeyError):
        return []

def _build_seed_info(seed: dict) -> dict:
    aid = (seed or {}).get("id") or ""
    md = (seed or {}).get("metadata") or {}
    return {
        "id": aid,
        "name": md.get("display_name"),
        "thumbnail": md.get("thumbnail_url"),
    }

def _dedupe_items(items: list, seen: set, id_key: str = "id") -> list:
    out = []
    for it in items:
        rid = (it.get(id_key) or it.get("browse_id") or it.get("browseId") or "").strip()
        if not rid or rid in seen:
            continue
        seen.add(rid)
        out.append(it)
    return out

def _build_result(seeds: dict, artists_out: list, albums_out: list) -> dict:
    return {
        "ok": True,
        "seed": {
            "artists": seeds.get("artists", []),
            "albums": seeds.get("albums", []),
        },
        "recommend": {
            "related_artists": artists_out,
            "related_albums": albums_out,
        },
    }

# -- IO ---------------------------------------------------
def _seed_artist_info(seed: dict, yt) -> dict:
    info = _build_seed_info(seed)
    if info.get("name") and info.get("thumbnail"):
        return info

    aid = info.get("id") or ""
    ckey = f"artist:header:{aid}"
    cached = get_cached_legacy(ckey)
    if cached:
        return {"id": aid, "name": cached.get("name"), "thumbnail": cached.get("thumb")}

    try:
        resp = yt.browse(aid) or {}
        header_info = _extract_header_info(resp)
        set_cached_legacy(ckey, header_info, 30 * 60)
        return {"id": aid, "name": header_info.get("name"), "thumbnail": header_info.get("thumb")}
    except Exception:
        return info


def _browse_artist_related(yt, artist_id: str, limit_each: int = 5) -> list:
    ckey = f"artist:related:{artist_id}"
    cached = get_cached_legacy(ckey)
    if cached is not None:
        return (cached or [])[:limit_each]

    try:
        resp = yt.browse(artist_id) or {}
        contents = _extract_contents(resp)
        rel_sec = pick_related_artists_section(contents)
        out = parse_related_artists(rel_sec)[:limit_each] if rel_sec else []
        set_cached_legacy(ckey, out, _RECO_TTL)
        return out
    except Exception:
        return []

def _get_album_recs(album_id: str, limit: int = 5) -> list:
    """related_recommendations de ytmusicapi, con fallback por artista."""
    ckey = f"album:recos:{album_id}"
    cached = get_cached_legacy(ckey)
    if cached is not None:
        return (cached or [])[:limit]

    try:
        parsed = music_client.get_album(album_id)
        recs = parsed.get("related_recommendations") or []

        if not recs:
            artist_ids = [a.get("id") for a in (parsed.get("artists") or []) if a.get("id")]
            if artist_ids:
                artist = music_client.get_artist(artist_ids[0])
                for r in (artist.get("related", {}).get("results", []) or [])[:3]:
                    rid = r.get("browseId")
                    if not rid:
                        continue
                    try:
                        rel_artist = music_client.get_artist(rid)
                        for a in (rel_artist.get("albums", {}).get("results", []) or [])[:2]:
                            recs.append(a)
                    except Exception:
                        continue

        out = recs[:limit]
        set_cached_legacy(ckey, out, _RECO_TTL if out else 5 * 60)
        return out
    except Exception:
        return []

def build_seed_recommendations(db: DBClient, user_id: str, per_seed: int = 5, per_type: int = 2) -> dict:
    seeds = recent_seeds_from_activity(db, user_id=user_id, per_type=per_type)
    yt = _ytm()

    # Artistas relacionados
    artists_out = []
    a_seen: set = set()
    for seed_artist in seeds.get("artists", []):
        aid = seed_artist.get("id")
        if not aid:
            continue
        similar_to = _seed_artist_info(seed_artist, yt)
        rel = _browse_artist_related(yt, aid, limit_each=per_seed)
        for it in _dedupe_items(rel, a_seen):
            it["similar_to"] = similar_to
            artists_out.append(it)
    artists_out = artists_out[:per_type * per_seed]

    # Albums relacionados
    albums_out = []
    al_seen: set = set()
    for al in seeds.get("albums", []):
        bid = al.get("id")
        if not bid:
            continue
        rel = _get_album_recs(bid, limit=per_seed)
        albums_out.extend(_dedupe_items(rel, al_seen, id_key="browseId"))
    albums_out = albums_out[:per_type * per_seed]

    return _build_result(seeds, artists_out, albums_out)