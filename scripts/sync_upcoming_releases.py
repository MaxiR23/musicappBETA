#!/usr/bin/env python3
"""
Sync de upcoming releases: Wikipedia -> enriquecimiento -> Supabase.

Scrapea albums de Wikipedia 2026, enriquece con covers y artist_id,
y sincroniza directo con Supabase (upsert inteligente).

- Albums released/postponed se saltean.
- Albums pending existentes se actualizan si hay metadata nueva.
- Albums nuevos con fecha pasada se confirman como released (con album_id) o postponed.
- Albums nuevos con fecha futura o TBA se insertan como pending.

Uso:
  python scripts/sync_upcoming_releases.py
  python scripts/sync_upcoming_releases.py --limit 10
  python scripts/sync_upcoming_releases.py --skip-enrichment
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path

import httpx
import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.supabase_service import supabase_service as sb
from services.upcoming_releases_repo import (
    get_released_and_postponed_keys,
    get_all_pending,
    insert_release,
    update_release_metadata,
    log_sync_error,
)
from shared.clients import _ytmusic_client

# ============================================================================
# CONFIGURATION
# ============================================================================

SHOW_DEBUG = False
DELAY_BETWEEN_ALBUMS = 20.0
DELAY_BETWEEN_REQUESTS = 1.5
DEFAULT_COVER_SIZE = 1200

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

UA = {"User-Agent": "Mozilla/5.0"}
COVER_SEARCH_URL = "https://itunes.apple.com/search"
COVER_LOOKUP_URL = "https://itunes.apple.com/lookup"
COUNTRIES = ["ar", "mx", "us", "es", "gb", "br", "fr", "de", "it", "pt", "ca", "au"]

# ============================================================================
# HELPERS
# ============================================================================

def dbg(*a):
    if SHOW_DEBUG:
        print("[DEBUG]", *a, file=sys.stderr, flush=True)


def norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\band\b", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\b(deluxe|clean|remaster(ed)?|remix(es)?|expanded|edition)\b", "", s).strip()
    return s


def upscale(url: str, size: int = 1200) -> str | None:
    if not url:
        return None
    return (
        url
        .replace("60x60bb", f"{size}x{size}bb")
        .replace("100x100bb", f"{size}x{size}bb")
        .replace("1400x1400bb", f"{size}x{size}bb")
    )


def is_past_release(release_date_str: str | None) -> bool:
    """True si la fecha de release ya paso."""
    if not release_date_str or release_date_str == "TBA":
        return False
    try:
        return date.fromisoformat(release_date_str) < date.today()
    except (ValueError, TypeError):
        return False


# ============================================================================
# WIKIPEDIA SCRAPING
# ============================================================================

def clean_text(text):
    text = re.sub(r"\[\d+\]", "", text).strip()
    text = re.sub(r"(\w)and([A-Z])", r"\1 and \2", text)
    text = re.sub(r"([a-z\d])and ", r"\1 and ", text)
    text = re.sub(r" and([A-Z])", r" and \1", text)
    return text


def parse_date_to_iso(date_str):
    if not date_str or date_str == "TBA":
        return date_str
    try:
        date_obj = datetime.strptime(f"{date_str} 2026", "%B%d %Y")
        return date_obj.strftime("%Y-%m-%d")
    except Exception:
        return date_str


def is_date_cell(text):
    text = text.strip()
    for month in MONTHS:
        if text.startswith(month):
            remainder = text[len(month):].strip()
            if remainder.isdigit():
                return True
    return False


def parse_dated_albums(table, current_date=None):
    albums = []
    for row in table.find_all("tr")[1:]:
        cols = row.find_all(["td", "th"])
        if len(cols) == 0:
            continue

        first_text = cols[0].get_text(strip=True)
        cell_is_date = is_date_cell(first_text) or cols[0].has_attr("rowspan")

        if cell_is_date:
            current_date = first_text
            artist = cols[1].get_text(strip=True) if len(cols) > 1 else ""
            album = cols[2].get_text(strip=True) if len(cols) > 2 else ""
            genre = cols[3].get_text(strip=True) if len(cols) > 3 else ""
            label = cols[4].get_text(strip=True) if len(cols) > 4 else ""
        else:
            artist = cols[0].get_text(strip=True) if len(cols) > 0 else ""
            album = cols[1].get_text(strip=True) if len(cols) > 1 else ""
            genre = cols[2].get_text(strip=True) if len(cols) > 2 else ""
            label = cols[3].get_text(strip=True) if len(cols) > 3 else ""

        if artist and album:
            artist = clean_text(artist)
            album = clean_text(album)
            genre = clean_text(genre)
            label = clean_text(label)

            if not current_date or current_date == "None":
                continue
            if not is_date_cell(current_date):
                continue
            if artist in ["TBA", "Artist", "None", "", "Release date"]:
                continue
            if album in ["TBA", "Album", "None", "", "Artist"]:
                continue
            if is_date_cell(artist):
                continue

            formatted_date = parse_date_to_iso(current_date)
            album_data = {"release_date": formatted_date, "artist": artist, "album": album}
            if genre:
                album_data["genre"] = genre
            if label:
                album_data["label"] = label
            albums.append(album_data)

    return albums


def parse_tba_albums(table):
    albums = []
    for row in table.find_all("tr")[1:]:
        cols = row.find_all(["td", "th"])
        if len(cols) < 2:
            continue

        artist = cols[0].get_text(strip=True)
        album = cols[1].get_text(strip=True) if len(cols) > 1 else ""
        genre = cols[2].get_text(strip=True) if len(cols) > 2 else ""
        label = cols[3].get_text(strip=True) if len(cols) > 3 else ""

        if artist and album:
            artist = clean_text(artist)
            album = clean_text(album)
            genre = clean_text(genre)
            label = clean_text(label)

            if artist in ["Artist", "None", ""]:
                continue
            if album in ["Album", "None", ""]:
                continue

            album_data = {"release_date": "TBA", "artist": artist, "album": album}
            if genre and genre != "TBA":
                album_data["genre"] = genre
            if label and label != "TBA":
                album_data["label"] = label
            albums.append(album_data)

    return albums


def scrape_wikipedia_albums():
    print("  Scrapeando Wikipedia...")
    url = "https://en.wikipedia.org/wiki/List_of_2026_albums"
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(response.content, "html.parser")

    dated_albums = []
    tba_albums = []
    tba_started = False

    for element in soup.find_all(["table", "h2", "h3"]):
        if element.name in ["h2", "h3"]:
            heading_text = element.get_text(strip=True)
            if "TBA" in heading_text or "Unreleased" in heading_text:
                tba_started = True
        elif element.name == "table" and "wikitable" in element.get("class", []):
            if tba_started:
                tba_albums.extend(parse_tba_albums(element))
            else:
                dated_albums.extend(parse_dated_albums(element))

    return dated_albums + tba_albums


# ============================================================================
# COVER SEARCH
# ============================================================================

def split_collab_artists(artist: str) -> list[str]:
    candidates = [artist]
    artist_no_parens = re.sub(r"\(.*?\)", "", artist).strip()
    parts = re.split(
        r"\s+(?:and|&|with|feat\.?|ft\.?|vs\.?)\s+",
        artist_no_parens,
        flags=re.IGNORECASE,
    )
    if len(parts) > 1:
        for p in parts:
            p = p.strip()
            if p and p not in candidates:
                candidates.append(p)
    return candidates


def search_cover_artist(artist: str) -> tuple[str, str] | None:
    aq = norm(artist)
    exacts = []
    with httpx.Client(headers=UA, timeout=20, follow_redirects=True) as c:
        for country in COUNTRIES:
            try:
                time.sleep(DELAY_BETWEEN_REQUESTS)
                r = c.get(COVER_SEARCH_URL, params={
                    "term": artist, "entity": "musicArtist", "limit": 10, "country": country,
                })
                if r.status_code == 429:
                    dbg(f"Rate limit en {country}, esperando 10s...")
                    time.sleep(10)
                    continue
                if r.status_code != 200:
                    continue
                for it in r.json().get("results", []):
                    if norm(it.get("artistName", "")) == aq:
                        exacts.append((it, country))
            except Exception:
                continue

        if not exacts:
            best = None
            for country in COUNTRIES:
                try:
                    time.sleep(DELAY_BETWEEN_REQUESTS)
                    r = c.get(COVER_SEARCH_URL, params={
                        "term": artist, "entity": "musicArtist", "limit": 10, "country": country,
                    })
                    if r.status_code == 429:
                        time.sleep(10)
                        continue
                    if r.status_code != 200:
                        continue
                    items = r.json().get("results", [])
                    if items:
                        items.sort(key=lambda x: int(x.get("artistId", 0)), reverse=True)
                        best = (items[0], country)
                        break
                except Exception:
                    continue
            return (str(best[0]["artistId"]), best[1]) if best else None

        seen = {}
        for it, country in exacts:
            seen.setdefault(str(it.get("artistId")), (it, set()))
            seen[str(it.get("artistId"))][1].add(country)

        def albums_count(artist_id: str, pref_country: str) -> tuple[int, str, int]:
            for cc in ("us", pref_country):
                try:
                    time.sleep(DELAY_BETWEEN_REQUESTS)
                    r = c.get(COVER_LOOKUP_URL, params={
                        "id": artist_id, "entity": "album", "limit": 200, "country": cc,
                    })
                    if r.status_code != 200:
                        continue
                    albs = [
                        x for x in r.json().get("results", [])
                        if x.get("wrapperType") == "collection" and x.get("collectionType") == "Album"
                    ]
                    max_cid = max([int(x.get("collectionId", 0)) for x in albs], default=0)
                    return (len(albs), cc, max_cid)
                except Exception:
                    continue
            return (0, pref_country, 0)

        scored = []
        for aid, (it, countries) in seen.items():
            cnt, used_cc, max_cid = albums_count(aid, next(iter(countries)))
            score = (cnt, int(used_cc == "us"), max_cid)
            scored.append((score, aid, used_cc))

        scored.sort(reverse=True)
        _, aid, cc = scored[0]
        return aid, cc


def lookup_artist_albums(artist_id: str, country: str) -> list[dict]:
    with httpx.Client(headers=UA, timeout=20, follow_redirects=True) as c:
        time.sleep(DELAY_BETWEEN_REQUESTS)
        r = c.get(COVER_LOOKUP_URL, params={
            "id": artist_id, "entity": "album", "limit": 200, "country": country,
        })
        r.raise_for_status()
        rows = [x for x in r.json().get("results", []) if x.get("wrapperType") == "collection"]
        return rows


def strict_pick_album(albums: list[dict], artist: str, album: str) -> dict | None:
    aq, tq = norm(artist), norm(album)
    albums = [x for x in albums if x.get("collectionType") == "Album"]
    if not albums:
        return None

    def score(x: dict):
        an = norm(x.get("artistName", ""))
        tn = norm(x.get("collectionName", ""))
        return (
            int(an == aq), int(tn == tq), int(tn.startswith(tq)), int(tq in tn),
            x.get("releaseDate", ""), int(x.get("collectionId", 0)),
        )

    albums.sort(key=score, reverse=True)
    top = albums[0]
    a_ok = norm(top.get("artistName", "")) == aq
    t_ok = norm(top.get("collectionName", "")) == tq
    ts_ok = norm(top.get("collectionName", "")).startswith(tq)
    if not (a_ok and (t_ok or ts_ok)):
        return None
    return top


def cover_by_artist_catalog(artist: str, album: str, size: int) -> dict | None:
    artist_found = search_cover_artist(artist)
    if not artist_found:
        return None
    artist_id, hint = artist_found
    order = [hint] + [c for c in COUNTRIES if c != hint]
    with httpx.Client(headers=UA, timeout=20, follow_redirects=True) as c:
        for country in order:
            try:
                albums = lookup_artist_albums(artist_id, country)
            except Exception:
                continue
            pick = strict_pick_album(albums, artist, album)
            if not pick:
                continue
            cid = pick.get("collectionId")
            if not cid:
                continue
            time.sleep(DELAY_BETWEEN_REQUESTS)
            r = c.get(COVER_LOOKUP_URL, params={"id": cid, "country": country})
            if r.status_code != 200:
                continue
            items = r.json().get("results", [])
            if not items:
                continue
            art = items[0].get("artworkUrl100") or items[0].get("artworkUrl60") or items[0].get("artworkUrl512")
            track_count = items[0].get("trackCount")
            if art:
                url = upscale(art, size)
                return {"thumbnail": url, "track_count": track_count}
    return None


def cover_by_text_search(
    artist: str, album: str, size: int,
    countries: list[str] | None = None,
    strict_artist: bool = True,
) -> dict | None:
    aq, tq = norm(artist), norm(album)
    search_countries = countries if countries is not None else COUNTRIES
    with httpx.Client(headers=UA, timeout=20, follow_redirects=True) as c:
        for country in search_countries:
            try:
                time.sleep(DELAY_BETWEEN_REQUESTS)
                r = c.get(COVER_SEARCH_URL, params={
                    "term": f"{artist} {album}", "media": "music",
                    "entity": "album", "limit": 200, "country": country,
                })
                if r.status_code == 429:
                    time.sleep(10)
                    continue
                if r.status_code != 200:
                    continue
                results = [
                    x for x in r.json().get("results", [])
                    if x.get("collectionType") == "Album"
                ]
                if not results:
                    continue

                def score(x: dict):
                    an = norm(x.get("artistName", ""))
                    tn = norm(x.get("collectionName", ""))
                    return (
                        int(an == aq), int(tn == tq), int(tn.startswith(tq)), int(tq in tn),
                        x.get("releaseDate", ""), int(x.get("collectionId", 0)),
                    )

                results.sort(key=score, reverse=True)
                top = results[0]
                an = norm(top.get("artistName", ""))
                tn = norm(top.get("collectionName", ""))
                a_ok = (an == aq) if strict_artist else True
                t_ok = tn == tq or tn.startswith(tq)
                if not (a_ok and t_ok):
                    continue
                cid = top.get("collectionId")
                if not cid:
                    continue
                time.sleep(DELAY_BETWEEN_REQUESTS)
                r2 = c.get(COVER_LOOKUP_URL, params={"id": cid, "country": country})
                if r2.status_code != 200:
                    continue
                items = r2.json().get("results", [])
                if not items:
                    continue
                art = (
                    items[0].get("artworkUrl100")
                    or items[0].get("artworkUrl60")
                    or items[0].get("artworkUrl512")
                )
                track_count = items[0].get("trackCount")
                if art:
                    url = upscale(art, size)
                    return {"thumbnail": url, "track_count": track_count}
            except Exception:
                continue
    return None


def get_album_cover(artist: str, album: str, size: int = DEFAULT_COVER_SIZE) -> dict | None:
    candidates = split_collab_artists(artist)

    result = cover_by_artist_catalog(candidates[0], album, size=size)
    if not result:
        result = cover_by_text_search(candidates[0], album, size=size, strict_artist=True)
    if result:
        return result

    for candidate in candidates[1:]:
        result = cover_by_text_search(
            candidate, album, size=size,
            countries=["us", "gb", "ar"],
            strict_artist=False,
        )
        if result:
            return result

    return None


# ============================================================================
# ARTIST ID + ALBUM ID SEARCH
# ============================================================================

def get_artist_id(artist: str) -> str | None:
    """Busca el artist_id (browseId) del artista."""
    try:
        results = _ytmusic_client().search(artist, filter="artists", limit=5)
        if not results:
            return None

        artist_norm = norm(artist)
        for result in results:
            if norm(result.get("artist", "")) == artist_norm:
                return result.get("browseId")

        return results[0].get("browseId")
    except Exception as e:
        dbg(f"Artist ID error for {artist}: {e}")
        return None


def get_album_id(artist_id: str, album_name: str) -> str | None:
    """Busca el album_id (browseId) en la discografia del artista."""
    if not artist_id or not album_name:
        return None
    try:
        artist_data = _ytmusic_client().get_artist(artist_id)
        albums = artist_data.get("albums", {}).get("results", [])
        singles = artist_data.get("singles", {}).get("results", [])[:3]
        all_releases = albums + singles
        if not all_releases:
            return None

        target = album_name.strip().lower()
        for release in all_releases:
            title = (release.get("title") or "").strip().lower()
            if title == target:
                return release.get("browseId")

        return None
    except Exception as e:
        dbg(f"Album ID error for {artist_id}/{album_name}: {e}")
        return None


# ============================================================================
# SYNC LOGIC
# ============================================================================

def map_to_db_row(album: dict) -> dict:
    """Mapea formato del scraper al schema de la DB."""
    release_date = album.get("release_date")
    is_tba = release_date == "TBA"

    return {
        "artist_name": album.get("artist"),
        "album_name": album.get("album"),
        "release_date": None if is_tba else release_date,
        "is_tba": is_tba,
        "label": album.get("label"),
        "genre": album.get("genre"),
        "artist_id": album.get("artist_id"),
        "album_id": album.get("album_id"),
        "thumbnail_url": album.get("thumbnail"),
        "track_count": album.get("track_count"),
        "status": album.get("status", "pending"),
        "enrichment_failed": album.get("enrichment_failed", False),
        "confirmed_at": album.get("confirmed_at"),
    }


def enrich_album(album: dict) -> dict:
    """Enriquece un album con cover y artist_id. Modifica in-place y retorna."""
    artist = album.get("artist", "")
    album_name = album.get("album", "")

    # Cover
    if not album.get("thumbnail"):
        try:
            cover_data = get_album_cover(artist, album_name)
            if cover_data:
                album["thumbnail"] = cover_data["thumbnail"]
                album["track_count"] = cover_data["track_count"]
            else:
                log_sync_error(sb, artist, album_name, "cover_not_found", "no match found")
        except Exception:
            log_sync_error(sb, artist, album_name, "cover_search_failed", "unexpected error during search")

    # Artist ID
    if not album.get("artist_id"):
        try:
            artist_id = get_artist_id(artist)
            if artist_id:
                album["artist_id"] = artist_id
            else:
                log_sync_error(sb, artist, album_name, "artist_id_not_found", "no match found")
        except Exception:
            log_sync_error(sb, artist, album_name, "artist_id_search_failed", "unexpected error during search")

    # Marcar si fallo algo
    if not album.get("thumbnail") or not album.get("artist_id"):
        album["enrichment_failed"] = True

    return album


def resolve_past_release(album: dict) -> dict:
    """Para albums con fecha pasada: busca album_id y asigna status released o postponed."""
    artist = album.get("artist", "")
    album_name = album.get("album", "")
    artist_id = album.get("artist_id")

    if artist_id:
        try:
            album_id = get_album_id(artist_id, album_name)
            if album_id:
                album["album_id"] = album_id
                album["status"] = "released"
                album["confirmed_at"] = datetime.now().isoformat()
                return album
        except Exception:
            log_sync_error(sb, artist, album_name, "album_id_search_failed", "unexpected error during search")

    # No encontro album_id -> postponed
    album["status"] = "postponed"
    album["confirmed_at"] = datetime.now().isoformat()
    if artist_id:
        log_sync_error(sb, artist, album_name, "album_id_not_found", "no match in artist discography")

    return album


def check_and_update_metadata(existing: dict, scraped: dict) -> bool:
    """Compara un pending existente con datos scrapeados. Actualiza si hay algo nuevo."""
    updates = {}

    # Pending con fecha pasada -> resolver como released o postponed
    existing_date = existing.get("release_date")
    if existing_date and is_past_release(existing_date):
        artist_id = existing.get("artist_id")
        album_name = existing.get("album_name", "")
        album_id = get_album_id(artist_id, album_name) if artist_id else None
        if album_id:
            updates["status"] = "released"
            updates["album_id"] = album_id
            updates["confirmed_at"] = datetime.now().isoformat()
        else:
            updates["status"] = "postponed"
            updates["confirmed_at"] = datetime.now().isoformat()
        return update_release_metadata(sb, existing["id"], updates)

    # TBA -> fecha concreta
    scraped_date = scraped.get("release_date")
    if scraped_date and scraped_date != "TBA":
        if existing.get("is_tba") or not existing.get("release_date"):
            updates["release_date"] = scraped_date
            updates["is_tba"] = False

    # Campos que se llenan si estaban vacios
    field_map = {
        "label": "label",
        "genre": "genre",
    }
    for scraped_key, db_key in field_map.items():
        scraped_val = scraped.get(scraped_key)
        if scraped_val and not existing.get(db_key):
            updates[db_key] = scraped_val

    if not updates:
        return False

    return update_release_metadata(sb, existing["id"], updates)

# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Sync upcoming releases")
    parser.add_argument("--limit", type=int, default=None, help="Procesar solo N albums (testing)")
    parser.add_argument("--skip-enrichment", action="store_true", help="Saltear busqueda de covers y artist_id")
    args = parser.parse_args()

    print("=" * 60)
    print("SYNC UPCOMING RELEASES")
    print("=" * 60)

    # 1. Scrapear Wikipedia
    print("\n[1/4] Scrapeando Wikipedia...")
    albums = scrape_wikipedia_albums()
    print(f"  Encontrados: {len(albums)}")

    if args.limit:
        albums = albums[:args.limit]
        print(f"  Limitado a: {len(albums)}")

    # 2. Cargar estado actual de DB
    print("\n[2/4] Cargando estado de DB...")
    closed_keys = get_released_and_postponed_keys(sb)
    pending_map = get_all_pending(sb)
    print(f"  Released/postponed: {len(closed_keys)}")
    print(f"  Pending: {len(pending_map)}")

    # 3. Procesar cada album
    print("\n[3/4] Procesando albums...")
    stats = {
        "skipped": 0, "inserted_pending": 0, "inserted_released": 0,
        "inserted_postponed": 0, "updated": 0, "enrichment_skipped": 0, "errors": 0,
    }
    new_count = 0

    for album in albums:
        key = (album.get("artist", ""), album.get("album", ""))
        if key not in closed_keys and key not in pending_map:
            new_count += 1

    if new_count > 0 and not args.skip_enrichment:
        estimated_min = new_count * 0.7
        print(f"  Nuevos a procesar: {new_count}")
        print(f"  Tiempo estimado: ~{estimated_min:.0f} minutos")
    print()

    for i, album in enumerate(albums, 1):
        artist = album.get("artist", "")
        album_name = album.get("album", "")
        key = (artist, album_name)

        # Ya cerrado -> skip
        if key in closed_keys:
            stats["skipped"] += 1
            continue

        # Ya pending -> ver si hay metadata nueva
        if key in pending_map:
            existing = pending_map[key]
            if check_and_update_metadata(existing, album):
                stats["updated"] += 1
            continue

        # Nuevo -> enriquecer e insertar
        processed = stats["inserted_pending"] + stats["inserted_released"] + stats["inserted_postponed"] + stats["errors"]
        print(f"  [{processed + 1}/{new_count}] {artist} - {album_name}", end=" ", flush=True)

        if args.skip_enrichment:
            album["enrichment_failed"] = True
            stats["enrichment_skipped"] += 1
        else:
            enrich_album(album)

        # Fecha pasada -> resolver como released o postponed
        if is_past_release(album.get("release_date")):
            resolve_past_release(album)

        row = map_to_db_row(album)
        if insert_release(sb, row):
            status = row.get("status", "pending")
            cover_flag = "C" if row.get("thumbnail_url") else "-"
            artist_flag = "A" if row.get("artist_id") else "-"
            album_id_flag = "I" if row.get("album_id") else "-"

            if status == "released":
                stats["inserted_released"] += 1
                print(f"[{cover_flag}{artist_flag}{album_id_flag}] RELEASED")
            elif status == "postponed":
                stats["inserted_postponed"] += 1
                print(f"[{cover_flag}{artist_flag}{album_id_flag}] POSTPONED")
            else:
                stats["inserted_pending"] += 1
                print(f"[{cover_flag}{artist_flag}]")
        else:
            stats["errors"] += 1
            log_sync_error(sb, artist, album_name, "insert_failed", "db insert error")
            print("[FAIL]")

        if not args.skip_enrichment and (processed + 1) < new_count:
            time.sleep(DELAY_BETWEEN_ALBUMS)

    # 4. Resumen
    print("\n" + "=" * 60)
    print("[4/4] RESUMEN:")
    print(f"  Total scrapeados:       {len(albums)}")
    print(f"  Skipped (cerrados):     {stats['skipped']}")
    print(f"  Pending actualizados:   {stats['updated']}")
    print(f"  Insertados pending:     {stats['inserted_pending']}")
    print(f"  Insertados released:    {stats['inserted_released']}")
    print(f"  Insertados postponed:   {stats['inserted_postponed']}")
    if stats["enrichment_skipped"]:
        print(f"  Sin enriquecimiento:    {stats['enrichment_skipped']}")
    print(f"  Errores:                {stats['errors']}")
    print("=" * 60)


if __name__ == "__main__":
    main()