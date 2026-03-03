# utils/events_upcoming.py
from __future__ import annotations
import os, time, requests
from typing import Any, Dict, List, Optional

class EventsError(RuntimeError):
    pass

def _tm_base() -> str:
    # default seguro si no seteaste TM_BASE en .env
    return os.getenv("TM_BASE") or "https://app.ticketmaster.com/discovery/v2"

def _api_key() -> str:
    k = os.getenv("EVENTS_API_KEY")
    if not k:
        raise EventsError("EVENTS_API_KEY no configurada")
    return k

def _pick_image(images: Optional[List[dict]]) -> Optional[str]:
    if not images:
        return None
    images = sorted(images, key=lambda x: -(x.get("width") or 0))
    return images[0].get("url")

def _find_attraction_id(artist_name: str, *, timeout: int = 20) -> str:
    r = requests.get(
        f"{_tm_base()}/attractions.json",
        params={"apikey": _api_key(), "keyword": artist_name, "size": 50},
        timeout=timeout,
    )
    r.raise_for_status()
    items = ((r.json().get("_embedded") or {}).get("attractions") or [])
    if not items:
        raise EventsError(f"Attraction no encontrada para: {artist_name}")

    name_cf = artist_name.casefold().strip()
    # preferir match exacto y segmento Music
    for a in items:
        seg = (((a.get("classifications") or [{}])[0]).get("segment") or {}).get("name", "")
        if a.get("name", "").casefold().strip() == name_cf and seg.lower() == "music":
            return a.get("id")
    # fallback: primera de segmento Music o primera
    for a in items:
        seg = (((a.get("classifications") or [{}])[0]).get("segment") or {}).get("name", "")
        if seg and seg.lower() == "music":
            return a.get("id")
    return items[0].get("id")

def _has_attraction(e: dict, attraction_id: str) -> bool:
    atts = ((e.get("_embedded") or {}).get("attractions") or [])
    return any(a.get("id") == attraction_id for a in atts if isinstance(a, dict))

def _normalize_event(e: dict) -> Dict[str, Any]:
    emb   = e.get("_embedded") or {}
    venues = emb.get("venues") or []
    v = venues[0] if venues else {}
    loc = v.get("location") or {}
    dates = e.get("dates") or {}
    start = dates.get("start") or {}
    end   = dates.get("end") or {}

    return {
        "id": e.get("id"),
        "name": e.get("name"),
        "url": e.get("url"),
        "image": _pick_image(e.get("images")),
        "start": {
            "local_date": start.get("localDate"),
            "local_time": start.get("localTime"),
            "timezone":  dates.get("timezone"),
            "utc":       start.get("dateTime"),
        },
        "end": {
            "local_date": end.get("localDate"),
            "local_time": end.get("localTime"),
            "utc":       end.get("dateTime"),
        },
        "status": (dates.get("status") or {}).get("code"),
        "venue": {
            "id": v.get("id"),
            "name": v.get("name"),
            "address": (v.get("address") or {}).get("line1"),
            "city": (v.get("city") or {}).get("name"),
            "state": (v.get("state") or {}).get("stateCode") or (v.get("state") or {}).get("name"),
            "country": (v.get("country") or {}).get("countryCode") or (v.get("country") or {}).get("name"),
            "postal_code": v.get("postalCode"),
            "timezone": v.get("timezone"),
            "lat": float(loc.get("latitude")) if loc.get("latitude") else None,
            "lon": float(loc.get("longitude")) if loc.get("longitude") else None,
        },
        "seatmap": (e.get("seatmap") or {}).get("staticUrl"),
        "price_ranges": e.get("priceRanges"),
        "attractions": [{"id": a.get("id"), "name": a.get("name")}
                        for a in (emb.get("attractions") or [])],
    }

def fetch_upcoming_events_by_artist(
    artist_name: str,
    limit: int = 12,
    *,
    timeout: int = 25,
    headliner_only: bool = False,
) -> Dict[str, Any]:
    """
    Devuelve { 'artist': str, 'attractionId': str, 'events': [..<=limit] }
    Filtra SOLO por attractionId oficial (sin heurísticas de texto).
    """
    aid = _find_attraction_id(artist_name, timeout=timeout)

    results: List[dict] = []
    page = 0
    while len(results) < limit:
        r = requests.get(
            f"{_tm_base()}/events.json",
            params={
                "apikey": _api_key(),
                "attractionId": aid,
                "classificationName": "Music",
                "sort": "date,asc",
                "size": 200,
                "page": page,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        evs = ((data.get("_embedded") or {}).get("events") or [])

        # mantener solo eventos que referencian el mismo attractionId
        filtered = []
        for e in evs:
            if not _has_attraction(e, aid):
                continue
            if headliner_only:
                atts = ((e.get("_embedded") or {}).get("attractions") or [])
                roles = [a.get("role","").lower() for a in atts if a.get("id")==aid]
                if roles and "headliner" not in roles:
                    continue
            filtered.append(e)

        results.extend(filtered)

        pg = data.get("page") or {}
        if page >= (pg.get("totalPages", 1) - 1):
            break
        page += 1
        time.sleep(0.15)

    return {
        "artist": artist_name,
        "attractionId": aid,
        "events": [_normalize_event(e) for e in results[:max(0, limit)]],
    }
