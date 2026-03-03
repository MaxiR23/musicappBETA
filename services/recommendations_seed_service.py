# services/recommendations_seed_service.py
from __future__ import annotations
from typing import Any, Dict, List, Optional

from shared.clients import _ytm
from services.cache_service import get_cached_legacy, set_cached_legacy
from services.activity_repo import recent_seeds_from_activity
from utils.artist_parser import parse_related_artists, pick_related_artists_section
from utils.album_parser import parse_album_releases_for_you

_RECO_TTL = 20 * 60  # 20 minutos

# ---------- Helpers ----------
def _seed_artist_info(seed: Dict[str, Any], yt) -> Dict[str, Optional[str]]:
    """
    Devuelve {id, name, thumbnail} del artista semilla.
    Usa metadata si viene; si falta, consulta header rápido.
    """
    aid = (seed or {}).get("id") or ""
    md  = (seed or {}).get("metadata") or {}
    name = md.get("display_name")
    thumb = md.get("thumbnail_url")

    if name and thumb:
        return {"id": aid, "name": name, "thumbnail": thumb}

    # fallback liviano: header del artista cacheado
    try:
        ckey = f"artist:header:{aid}"
        cached = get_cached_legacy(ckey)
        if cached:
            return {"id": aid, "name": cached.get("name"), "thumbnail": cached.get("thumb")}

        resp = yt.browse(aid) or {}
        header = resp.get("header", {}).get("musicImmersiveHeaderRenderer", {})
        runs = (header.get("title", {}) or {}).get("runs", []) or [{}]
        h_name = runs[0].get("text")
        thumbs = (
            header.get("thumbnail", {})
                  .get("musicThumbnailRenderer", {})
                  .get("thumbnail", {})
                  .get("thumbnails", []) or []
        )
        h_thumb = (thumbs[-1] or {}).get("url") if thumbs else None
        set_cached_legacy(ckey, {"name": h_name, "thumb": h_thumb}, 30 * 60)
        return {"id": aid, "name": h_name, "thumbnail": h_thumb}
    except Exception:
        return {"id": aid, "name": name or None, "thumbnail": thumb or None}

def _browse_artist_related(yt, artist_id: str, limit_each: int = 5) -> List[Dict[str, Any]]:
    ckey = f"artist:related:{artist_id}"
    cached = get_cached_legacy(ckey)
    if cached is not None:
        return (cached or [])[:limit_each]

    resp = yt.browse(artist_id) or {}
    contents = (
        resp.get("contents", {})
            .get("singleColumnBrowseResultsRenderer", {})
            .get("tabs", [])[0]
            .get("tabRenderer", {})
            .get("content", {})
            .get("sectionListRenderer", {})
            .get("contents", [])
    )
    rel_sec = pick_related_artists_section(contents)
    out = parse_related_artists(rel_sec)[:limit_each] if rel_sec else []
    set_cached_legacy(ckey, out, _RECO_TTL)
    return out

def _browse_album_related(yt, album_id: str, limit_each: int = 5) -> List[Dict[str, Any]]:
    """
    Por ahora solo 'Releases For You' (sin similar_to). Lo de álbumes se mejora después.
    """
    ckey = f"album:recos:{album_id}"
    cached = get_cached_legacy(ckey)
    if cached is not None:
        return (cached or [])[:limit_each]

    resp = yt.browse(album_id) or {}
    rel_for_you = parse_album_releases_for_you(resp) or []
    out = rel_for_you[:limit_each] if rel_for_you else []
    set_cached_legacy(ckey, out, _RECO_TTL if out else 5 * 60)
    return out

# ---------- API del servicio ----------
def build_seed_recommendations(
    user_id: str,
    per_seed: int = 5,
    per_type: int = 2,   # cuántos seeds por tipo (artist/album)
    lookback: int = 400,
) -> Dict[str, Any]:
    """
    Devuelve:
      - seed.{artists, albums} (hasta per_type cada uno)
      - recommend.related_artists: cada item incluye 'similar_to' = {id,name,thumbnail} del seed-artist
      - recommend.related_albums: como vienen del parser (sin similar_to por ahora)
    """
    seeds = recent_seeds_from_activity(user_id=user_id, per_type=per_type, lookback=lookback)
    yt = _ytm()

    # ----- Artists (enriquecidos con similar_to) -----
    artists_out: List[Dict[str, Any]] = []
    a_seen: set[str] = set()
    for seed_artist in seeds.get("artists", []):
        aid = seed_artist.get("id")
        if not aid:
            continue
        similar_to = _seed_artist_info(seed_artist, yt)
        rel = _browse_artist_related(yt, aid, limit_each=per_seed)
        for it in rel:
            rid = (it.get("id") or it.get("browse_id") or "").strip()
            if not rid or rid in a_seen:
                continue
            a_seen.add(rid)
            enriched = dict(it)
            enriched["similar_to"] = similar_to
            artists_out.append(enriched)
    artists_out = artists_out[: per_type * per_seed]

    # ----- Albums (sin similar_to por ahora) -----
    albums_out: List[Dict[str, Any]] = []
    al_seen: set[str] = set()
    for al in seeds.get("albums", []):
        bid = al.get("id")
        if not bid:
            continue
        rel = _browse_album_related(yt, bid, limit_each=per_seed)
        for it in rel:
            rid = (it.get("id") or it.get("browse_id") or "").strip()
            if not rid or rid in al_seen:
                continue
            al_seen.add(rid)
            albums_out.append(it)
    albums_out = albums_out[: per_type * per_seed]

    return {
        "ok": True,
        "seed": {
            "artists": seeds.get("artists", []),
            "albums":  seeds.get("albums", []),
        },
        "recommend": {
            "related_artists": artists_out,
            "related_albums":  albums_out,
        },
    }