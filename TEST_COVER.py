#!/usr/bin/env python3
# TEST_COVER.py
# deps: pip install httpx
from __future__ import annotations
import sys, argparse, unicodedata, re, json
import httpx

UA = {"User-Agent": "Mozilla/5.0"}
ITUNES_SEARCH = "https://itunes.apple.com/search"
ITUNES_LOOKUP = "https://itunes.apple.com/lookup"

# storefronts razonables
COUNTRIES = ["ar","mx","us","es","gb","br","fr","de","it","pt","ca","au"]

DEBUG = False
def dbg(*a):
    if DEBUG:
        print("[DEBUG]", *a, file=sys.stderr, flush=True)

def norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\b(deluxe|clean|remaster(ed)?|remix(es)?|expanded|edition)\b", "", s).strip()
    return s

def upscale(url: str, size: int = 1200) -> str | None:
    if not url: return None
    return (url
        .replace("60x60bb", f"{size}x{size}bb")
        .replace("100x100bb", f"{size}x{size}bb")
        .replace("1400x1400bb", f"{size}x{size}bb"))

def search_artist_id(artist: str) -> tuple[str,str] | None:
    aq = norm(artist)
    exacts = []  # [(artist_obj, country)]
    with httpx.Client(headers=UA, timeout=20, follow_redirects=True) as c:
        for country in COUNTRIES:
            r = c.get(ITUNES_SEARCH, params={
                "term": artist, "entity": "musicArtist", "limit": 10, "country": country
            })
            if r.status_code != 200:
                continue
            for it in r.json().get("results", []):
                if norm(it.get("artistName","")) == aq:
                    exacts.append((it, country))

        if not exacts:
            # fallback al "mejor suelto" (como antes)
            best = None
            for country in COUNTRIES:
                r = c.get(ITUNES_SEARCH, params={
                    "term": artist, "entity": "musicArtist", "limit": 10, "country": country
                })
                if r.status_code != 200: 
                    continue
                items = r.json().get("results", [])
                if items:
                    items.sort(key=lambda x: int(x.get("artistId",0)), reverse=True)
                    best = (items[0], country)
                    break
            return (str(best[0]["artistId"]), best[1]) if best else None

        # Deduplicar por artistId
        seen = {}
        for it, country in exacts:
            seen.setdefault(str(it.get("artistId")), (it, set()))
            seen[str(it.get("artistId"))][1].add(country)

        # Score por "riqueza de catálogo": #álbumes reales en US (si se puede) o en el primer país visto
        def albums_count(artist_id: str, pref_country: str) -> tuple[int, str, int]:
            for cc in ( "us", pref_country ):
                try:
                    r = c.get(ITUNES_LOOKUP, params={
                        "id": artist_id, "entity": "album", "limit": 200, "country": cc
                    })
                    if r.status_code != 200:
                        continue
                    albums = [x for x in r.json().get("results", []) 
                              if x.get("wrapperType")=="collection" and x.get("collectionType")=="Album"]
                    # Tie-break adicional: colección más nueva (collectionId máximo)
                    max_cid = max([int(x.get("collectionId",0)) for x in albums], default=0)
                    return (len(albums), cc, max_cid)
                except Exception:
                    continue
            return (0, pref_country, 0)

        scored = []
        for aid, (it, countries) in seen.items():
            cnt, used_cc, max_cid = albums_count(aid, next(iter(countries)))
            # score: más álbumes > US preferido > mayor cid
            score = (cnt, int(used_cc=="us"), max_cid)
            scored.append((score, aid, used_cc))

        scored.sort(reverse=True)
        # devuelve el artistId "rico" y el país que funcionó mejor
        _, aid, cc = scored[0]
        return aid, cc

def lookup_artist_albums(artist_id: str, country: str) -> list[dict]:
    with httpx.Client(headers=UA, timeout=20, follow_redirects=True) as c:
        r = c.get(ITUNES_LOOKUP, params={
            "id": artist_id,
            "entity": "album",
            "limit": 200,
            "country": country,
        })
        r.raise_for_status()
        rows = [x for x in r.json().get("results", []) if x.get("wrapperType")=="collection"]
        dbg("albums in", country, ":", len(rows))
        return rows

def strict_pick_album(albums: list[dict], artist: str, album: str) -> dict | None:
    aq, tq = norm(artist), norm(album)
    albums = [x for x in albums if x.get("collectionType")=="Album"]
    dbg("albums after type==Album:", len(albums))
    if not albums: return None

    def score(x: dict):
        an = norm(x.get("artistName",""))
        tn = norm(x.get("collectionName",""))
        exact_title = int(tn == tq)
        starts_title = int(tn.startswith(tq))
        contains_title = int(tq in tn)
        exact_artist = int(an == aq)
        cid = int(x.get("collectionId",0))
        rdate = x.get("releaseDate","")
        return (exact_artist, exact_title, starts_title, contains_title, rdate, cid)

    # Log top-5 candidatos antes de decidir
    preview = sorted(albums, key=score, reverse=True)[:5]
    for i, it in enumerate(preview, 1):
        dbg(f"cand#{i}",
            "artist=", it.get("artistName"),
            "| title=", it.get("collectionName"),
            "| rdate=", it.get("releaseDate"),
            "| cid=", it.get("collectionId"),
            "| score=", score(it))

    albums.sort(key=score, reverse=True)
    top = albums[0]
    a_ok = (norm(top.get("artistName","")) == aq)
    t_ok = (norm(top.get("collectionName","")) == tq)
    ts_ok = norm(top.get("collectionName","")).startswith(tq)
    if not (a_ok and (t_ok or ts_ok)):
        dbg("top candidate rejected by strict check:",
            "artist=", top.get("artistName"), "title=", top.get("collectionName"))
        return None
    dbg("top candidate ACCEPTED:",
        "artist=", top.get("artistName"), "title=", top.get("collectionName"), "cid=", top.get("collectionId"))
    return top

def apple_cover_by_artist_catalog(artist: str, album: str, size: int) -> dict | None:
    artist_found = search_artist_id(artist)
    if not artist_found:
        dbg("artist not found at all")
        return None
    artist_id, hint = artist_found
    order = [hint] + [c for c in COUNTRIES if c != hint]
    with httpx.Client(headers=UA, timeout=20, follow_redirects=True) as c:
        for country in order:
            try:
                albums = lookup_artist_albums(artist_id, country)
            except Exception as e:
                dbg("lookup albums error", country, repr(e))
                continue
            pick = strict_pick_album(albums, artist, album)
            if not pick:
                dbg("no acceptable album in", country)
                continue
            cid = pick.get("collectionId")
            if not cid:
                dbg("missing collectionId in pick", country)
                continue
            r = c.get(ITUNES_LOOKUP, params={"id": cid, "country": country})
            if r.status_code != 200:
                dbg("final lookup failed", country, r.status_code)
                continue
            items = r.json().get("results", [])
            if not items:
                dbg("final lookup empty", country)
                continue
            art = items[0].get("artworkUrl100") or items[0].get("artworkUrl60") or items[0].get("artworkUrl512")
            track_count = items[0].get("trackCount")
            if art:
                url = upscale(art, size)
                dbg("OK cover from", country, "=>", url, "trackCount=", track_count)
                return {"thumbnail": url, "track_count": track_count}
    return None

def apple_cover_by_text_search(artist: str, album: str, size: int) -> dict | None:
    aq, tq = norm(artist), norm(album)
    with httpx.Client(headers=UA, timeout=20, follow_redirects=True) as c:
        for country in COUNTRIES:
            r = c.get(ITUNES_SEARCH, params={
                "term": f"{artist} {album}",
                "media":"music",
                "entity":"album",
                "limit":200,
                "country": country
            })
            if r.status_code != 200:
                dbg("text search failed", country, r.status_code)
                continue
            results = [x for x in r.json().get("results", []) if x.get("collectionType")=="Album"]
            dbg("text search albums in", country, ":", len(results))
            if not results:
                continue
            def score(x: dict):
                an = norm(x.get("artistName","")); tn = norm(x.get("collectionName",""))
                exact_title = int(tn == tq)
                starts_title = int(tn.startswith(tq))
                contains_title = int(tq in tn)
                exact_artist = int(an == aq)
                cid = int(x.get("collectionId",0))
                rdate = x.get("releaseDate","")
                return (exact_artist, exact_title, starts_title, contains_title, rdate, cid)
            results.sort(key=score, reverse=True)
            # log top-3
            for i, it in enumerate(results[:3], 1):
                dbg(f"text cand#{i}",
                    "artist=", it.get("artistName"), "title=", it.get("collectionName"),
                    "rdate=", it.get("releaseDate"), "cid=", it.get("collectionId"), "score=", score(it))
            top = results[0]
            a_ok = (norm(top.get("artistName","")) == aq)
            t_ok = (norm(top.get("collectionName","")) == tq)
            ts_ok = norm(top.get("collectionName","")).startswith(tq)
            if not (a_ok and (t_ok or ts_ok)):
                dbg("text top rejected by strict check")
                continue
            cid = top.get("collectionId")
            if not cid:
                dbg("text top missing cid")
                continue
            r2 = c.get(ITUNES_LOOKUP, params={"id": cid, "country": country})
            if r2.status_code != 200:
                dbg("text final lookup failed", country, r2.status_code)
                continue
            items = r2.json().get("results", [])
            if not items:
                dbg("text final lookup empty", country)
                continue
            art = items[0].get("artworkUrl100") or items[0].get("artworkUrl60") or items[0].get("artworkUrl512")
            track_count = items[0].get("trackCount")
            if art:
                url = upscale(art, size)
                dbg("OK cover (text) from", country, "=>", url, "trackCount=", track_count)
                return {"thumbnail": url, "track_count": track_count}
    return None

def main():
    global DEBUG
    ap = argparse.ArgumentParser(description="Cover URL desde iTunes/Apple Music (solo iTunes, estricto).")
    ap.add_argument("artist")
    ap.add_argument("album")
    ap.add_argument("--size", type=int, default=1200)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    DEBUG = args.debug

    result = apple_cover_by_artist_catalog(args.artist, args.album, size=args.size)
    if not result:
        dbg("catalog flow NOT_FOUND → trying text search fallback…")
        result = apple_cover_by_text_search(args.artist, args.album, size=args.size)

    if result:
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0)
    else:
        print("NOT_FOUND")
        sys.exit(1)

if __name__ == "__main__":
    main()