# utils/feed_utils.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Callable
import re, unicodedata
from services.music_lookup import MusicLookup as Catalog
import time  # import local para no tocar globales

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

    # helpers locales para NO tocar nada más del archivo
    def _strip_qualifiers(t: str) -> str:
        # saca sufijos comunes: (deluxe), deluxe edition, expanded, remastered, soundtrack, epilogue, etc.
        t = re.sub(r'\((deluxe|expanded|remaster(?:ed)?|edition|epilogue|soundtrack|original motion picture|omps)\)', ' ', t, flags=re.I)
        t = re.sub(r'\b(deluxe|expanded|remaster(?:ed)?|edition|epilogue|soundtrack|original motion picture|omps)\b', ' ', t, flags=re.I)
        return re.sub(r'\s+', ' ', t).strip()

    ROMAN = {'ii': '2','iii':'3','iv':'4','v':'5','vi':'6','vii':'7','viii':'8','ix':'9','x':'10'}
    def _normalize_numerals(t: str) -> str:
        # “II” -> “2”, “V”->“5”, etc. (en minúsculas ya por norm)
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
        # contains/startswith para casos “deluxe/expanded/…”
        return a2 in b2 or b2 in a2 or a2.startswith(b2) or b2.startswith(a2)

    pick = None
    for lim in (25, 50, 100):  # ampliamos pool
        hits = Catalog.search_albums(f"{artist} {title}", limit=lim) or []

        # 1) match exacto + artista
        for h in hits:
            t = norm(h.get("title", ""))
            arts = h.get("artists") or []
            got = artist_tokens(", ".join(a.get("name", "") for a in arts if isinstance(a, dict)))
            if t == want_title and (want_artset & got):
                pick = h; break
        if pick: break

        # 2) fallback tolerante por título + cruce de artista
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

    info = Catalog.get_album(bid) or {}
    artist_objs  = [a for a in (info.get("artists") or []) if isinstance(a, dict)]
    artist_names = [a.get("name","") for a in artist_objs if a.get("name")]
    artist_ids   = [a.get("id") for a in artist_objs if a.get("id")]
    thumbs = info.get("thumbnails") or (info.get("thumbnail", {}).get("thumbnails") or [])

    return {
        "id": bid,
        "type": "album",
        "title": info.get("title") or title,
        "artist": ", ".join(artist_names) or artist,   
        "artistId": artist_ids[0] if artist_ids else None,  #TODO: add two ids if its necessary.
        "year": info.get("year") or "",
        "track_count": info.get("track_count") or "",
        "thumb": last_thumb(thumbs),
        "url": f"/browse/{bid}",
    }

def map_track(artist: str, title: str) -> Optional[Dict[str, Any]]:
    res = Catalog.search_songs(f"{artist} {title}", limit=1)
    if not res: return None
    vid = Catalog.first_song_id(res)
    if not vid: return None
    s = Catalog.get_song(vid) or {}
    micro = (s.get("microformat", {}) or {}).get("microformatDataRenderer", {}) or {}
    vdet  = s.get("videoDetails") or {}
    song_details = s.get("songDetails", {}) or {}
    artists = song_details.get("artists") or res[0].get("artists") or []
    artist_names = [a.get("name","") for a in artists if isinstance(a, dict)]
    artist_id = (artists[0].get("id") if isinstance(artists, list) and artists else None) \
                or ((res[0].get("artists") or [{}])[0].get("id"))
    album_name = (song_details.get("album") or {}).get("name") or (res[0].get("album") or {}).get("name", "")
    dur = micro.get("lengthSeconds") or vdet.get("lengthSeconds") or ""
    def _fmt_mmss(val): 
        try: sec=int(val); return f"{sec//60}:{sec%60:02d}"
        except: return ""
    hit_thumbs = res[0].get("thumbnails") or []
    def _pick_lh3(ths):
        if not ths: return ""
        lh3 = [t for t in ths if "lh3.googleusercontent.com" in str((t or {}).get("url",""))]
        cand = lh3 if lh3 else ths
        best = max((c for c in cand if isinstance(c, dict)), key=lambda t: int((t.get("width") or 0)), default={})
        return best.get("url","") or ""
    return {
        "id": vid, "type": "track",
        "title": vdet.get("title") or res[0].get("title","") or title,
        "artist": ", ".join([n for n in artist_names if n]) or artist,
        "artistId": artist_id, "album": album_name,
        "duration": _fmt_mmss(dur),
        "duration_s": int(dur) if str(dur).isdigit() else None,
        "thumb": _pick_lh3(hit_thumbs), "url": f"/watch/{vid}",
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
            
            # ✅ Cortar cuando llegue a la meta
            if len(out) >= want:
                if on_limit_reached:
                    on_limit_reached(len(out))
                break  # ← Ahora SÍ cortamos

        if micro_pause and (i % 3 == 2):
            time.sleep(micro_pause)

    return out