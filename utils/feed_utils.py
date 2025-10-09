# utils/feed_utils.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
import re, unicodedata
from services.music_lookup import MusicLookup as Catalog

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
    hits = Catalog.search_albums(f"{artist} {title}", limit=8) or []
    pick = None
    for h in hits:
        t = norm(h.get("title", ""))
        arts = h.get("artists") or []
        got = artist_tokens(", ".join(a.get("name", "") for a in arts if isinstance(a, dict)))
        if t == want_title and (want_artset & got):
            pick = h; break
    if not pick: return None
    bid = pick.get("browseId")
    if not bid: return None
    info = Catalog.get_album(bid) or {}
    artist_names = [a.get("name","") for a in (info.get("artists") or []) if isinstance(a, dict)]
    thumbs = info.get("thumbnails") or (info.get("thumbnail", {}).get("thumbnails") or [])
    return {
        "id": bid, "type": "album",
        "title": info.get("title") or title,
        "artist": ", ".join([n for n in artist_names if n]) or artist,
        "year": info.get("year") or "", "track_count": info.get("track_count") or "",
        "thumb": last_thumb(thumbs), "url": f"/browse/{bid}",
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