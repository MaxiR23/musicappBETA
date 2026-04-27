# utils/feed_utils.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Callable
import re, unicodedata
import json
import random
import time
from shared.clients import _ytmusic_client


def _with_retry(fn, *args, max_attempts: int = 5, base_delay: float = 1.0, **kwargs):
    """
    Reintenta ante JSONDecodeError (YT devuelve HTML en vez de JSON, intermitente).
    Backoff exponencial con jitter: ~1s, ~2s.
    """
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except json.JSONDecodeError as e:
            last_exc = e
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1)) * random.uniform(0.7, 1.3)
                time.sleep(delay)
    raise last_exc


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return re.sub(r'[\s\-\–\—\._"\'\[\]\(\)]+', ' ', s.lower()).strip()

def artist_tokens(s: str) -> set[str]:
    return set(t.strip() for t in re.split(r"[,&/]| feat\. | ft\. ", s.lower()) if t.strip())

def last_thumb(thumbnails: Optional[List[Dict[str, Any]]]) -> str:
    if not thumbnails: return ""
    return (thumbnails[-1] or {}).get("url", "") or ""

def map_album(artist: str, title: str) -> Optional[Dict[str, Any]]:
    want_title  = norm(title)
    want_artset = artist_tokens(artist)

    # helpers locales para NO tocar nada mas del archivo
    def _strip_qualifiers(t: str) -> str:
        # saca sufijos comunes: (deluxe), deluxe edition, expanded, remastered, soundtrack, epilogue, etc.
        t = re.sub(r'\((deluxe|expanded|remaster(?:ed)?|edition|epilogue|soundtrack|original motion picture|omps)\)', ' ', t, flags=re.I)
        t = re.sub(r'\b(deluxe|expanded|remaster(?:ed)?|edition|epilogue|soundtrack|original motion picture|omps)\b', ' ', t, flags=re.I)
        return re.sub(r'\s+', ' ', t).strip()

    ROMAN = {'ii': '2','iii':'3','iv':'4','v':'5','vi':'6','vii':'7','viii':'8','ix':'9','x':'10'}
    def _normalize_numerals(t: str) -> str:
        # "II" -> "2", "V" -> "5", etc. (en minusculas ya por norm)
        parts = t.split()
        out = []
        for p in parts:
            out.append(ROMAN.get(p, p))
        return ' '.join(out)

    def _titles_match(a: str, b: str) -> bool:
        # compara con tolerancia
        a0, b0 = a, b
        if a0 == b0:  # exacto
            return True
        a1, b1 = _strip_qualifiers(a0), _strip_qualifiers(b0)
        if a1 == b1:  # exacto sin qualifiers
            return True
        a2, b2 = _normalize_numerals(a1), _normalize_numerals(b1)
        # contains/startswith para casos "deluxe/expanded/..."
        return a2 in b2 or b2 in a2 or a2.startswith(b2) or b2.startswith(a2)

    pick = None
    for lim in (25, 50, 100):  # ampliamos pool
        hits = _ytmusic_client().search(f"{artist} {title}", filter="albums", limit=lim) or []

        # 1) match exacto + artista
        for h in hits:
            t = norm(h.get("title", ""))
            arts = h.get("artists") or []
            got = artist_tokens(", ".join(a.get("name", "") for a in arts if isinstance(a, dict)))
            if t == want_title and (want_artset & got):
                pick = h; break
        if pick: break

        # 2) fallback tolerante por titulo + cruce de artista
        for h in hits:
            t = norm(h.get("title", ""))
            arts = h.get("artists") or []
            got = artist_tokens(", ".join(a.get("name", "") for a in arts if isinstance(a, dict)))
            if (want_artset & got) and _titles_match(want_title, t):
                pick = h; break
        if pick: break

        # pausa discreta solo una vez
        if lim == 25:
            time.sleep(3)

    if not pick:
        return None

    bid = pick.get("browseId")
    if not bid:
        return None

    info = _ytmusic_client().get_album(bid) or {}
    artist_objs = [a for a in (info.get("artists") or []) if isinstance(a, dict)]
    thumbs = info.get("thumbnails") or (info.get("thumbnail", {}).get("thumbnails") or [])

    return {
        "id": bid,
        "type": "album",
        "title": info.get("title") or title,
        "artists": [
            {"id": a.get("id"), "name": a.get("name")}
            for a in artist_objs
            if a.get("name")
        ],
        "year": info.get("year") or "",
        "thumbnail": last_thumb(thumbs),
    }

def map_track(artist: str, title: str) -> Optional[Dict[str, Any]]:
    results = _with_retry(
        _ytmusic_client().search,
        f"{artist} {title}",
        filter="songs",
        limit=1,
    )
    if not results:
        return None

    hit = results[0]
    video_id = hit.get("videoId")
    if not video_id:
        return None

    artists = hit.get("artists") or []
    album = hit.get("album") or {}
    thumbnails = hit.get("thumbnails") or []

    return {
        "id": video_id,
        "track_id": video_id,
        "type": "track",
        "title": hit.get("title") or title,
        "artists": [
            {"id": a.get("id"), "name": a.get("name")}
            for a in artists
            if a.get("name")
        ],
        "album": album.get("name"),
        "album_id": album.get("id"),
        "duration_seconds": hit.get("duration_seconds"),
        "thumbnail_url": thumbnails[-1].get("url") if thumbnails else None,
    }

def map_albums_until(
    pairs: List[Dict[str, str]],
    want: int = 25,
    micro_pause: float = 0.4,
    on_limit_reached: Optional[Callable[[int], None]] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()

    for i, p in enumerate(pairs):
        artist = (p.get("artist") or "").strip()
        title  = (p.get("title") or "").strip()
        if not artist or not title:
            continue

        mapped = map_album(artist, title)
        if mapped and (mid := mapped.get("id")) and mid not in seen_ids:
            out.append(mapped)
            seen_ids.add(mid)

            # cortar cuando llegue a la meta
            if len(out) >= want:
                if on_limit_reached:
                    on_limit_reached(len(out))
                break  # Ahora SI cortamos

        if micro_pause and (i % 3 == 2):
            time.sleep(micro_pause)

    return out