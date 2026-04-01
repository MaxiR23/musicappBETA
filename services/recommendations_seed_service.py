from __future__ import annotations

from services import music_client
from services.db_protocol import DBClient
from services.cache_service import get_cached_legacy, set_cached_legacy
from services.activity_repo import recent_seeds_from_activity

_RECO_TTL = 20 * 60

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

def _upgrade_artist_thumb(url: str | None, size: int = 300) -> str | None:
    if not url or "lh3.googleusercontent.com" not in url:
        return url
    return f"{url.split('=')[0]}=w{size}-h{size}-l90-rj"

# -- IO ---------------------------------------------------
def _get_artist_data(artist_id: str, per_seed: int = 5) -> tuple[dict, list]:
    """Devuelve (seed_info, related_artists) usando ytmusicapi."""
    ckey = f"artist:data:{artist_id}"
    cached = get_cached_legacy(ckey)
    if cached is not None:
        return cached["info"], (cached.get("related") or [])[:per_seed]

    try:
        artist = music_client.get_artist(artist_id)
        thumbs = artist.get("thumbnails") or []
        info = {
            "id": artist_id,
            "name": artist.get("name"),
            "thumbnail": _upgrade_artist_thumb(thumbs[-1]["url"]) if thumbs else None,
        }
        related = (artist.get("related", {}).get("results") or [])[:per_seed]
        set_cached_legacy(ckey, {"info": info, "related": related}, _RECO_TTL)
        return info, related
    except Exception:
        return {"id": artist_id, "name": None, "thumbnail": None}, []

def _get_album_recs(album_id: str, limit: int = 5) -> list:
    """related_recommendations de ytmusicapi, con fallback por artista."""
    ckey = f"album:recos:{album_id}"
    cached = get_cached_legacy(ckey)
    if cached is not None:
        return (cached or [])[:limit]

    try:
        parsed = music_client.get_album(album_id)
        recs = parsed.get("related_recommendations") or []

        for rec in recs:
            if not rec.get("artist_name"):
                artists = rec.get("artists") or []
                if artists:
                    rec["artist_name"] = artists[0].get("name")

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
                        rel_name = rel_artist.get("name")
                        for a in (rel_artist.get("albums", {}).get("results", []) or [])[:2]:
                            a["artist_name"] = rel_name
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

    # Artistas relacionados
    artists_out = []
    a_seen: set = set()
    for seed_artist in seeds.get("artists", []):
        aid = seed_artist.get("id")
        if not aid:
            continue
        similar_to, rel = _get_artist_data(aid, per_seed=per_seed)
        for it in _dedupe_items(rel, a_seen, id_key="browseId"):
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