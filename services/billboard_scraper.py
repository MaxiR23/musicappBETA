# services/billboard_scraper.py
# deps: pip install httpx selectolax
from __future__ import annotations

import sys
import re
import time
from typing import List, Dict, Optional, Tuple
import httpx
from selectolax.parser import HTMLParser

BASE_URL = "https://www.billboard.com/charts/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/123.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# Cache simple (TTL en segundos)
_CACHE: Dict[str, Dict[str, object]] = {}
TTL_SECONDS = 15 * 60

# Solo CHARTS de MÚSICA (whitelist)
MUSIC_SLUG_ALLOWLIST = {
    # Songs (global / US / metrics):
    "hot-100", "global-200", "global-excl-us",
    "streaming-songs", "radio-songs", "digital-song-sales",
    # Albums:
    "billboard-200", "top-album-sales", "vinyl-albums", "soundtracks",
    # Artists:
    "artist-100",
    # Géneros (ejemplos más comunes):
    "hot-latin-songs", "latin-airplay", "top-latin-albums",
    "hot-country-songs", "country-airplay", "top-country-albums",
    "hot-r-and-b-hip-hop-songs", "r-and-b-songs", "rap-song-sales",
    "hot-rock-songs", "hot-alternative-songs", "top-rock-albums",
    # Regionales conocidos:
    "argentina-hot-100"
}


def _get_html(url: str, retries: int = 3, timeout: float = 15.0) -> str:
    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        try:
            with httpx.Client(headers=HEADERS, timeout=timeout, follow_redirects=True) as client:
                r = client.get(url)
                r.raise_for_status()
                return r.text
        except Exception as e:
            last_exc = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"HTTP error fetching {url}: {last_exc}")


def _norm(s: str) -> str:
    return " ".join((s or "").split())


def _extract_items_generic(doc: HTMLParser) -> List[HTMLParser]:
    # Items de la lista principal (varía por layout)
    items = doc.css("li.o-chart-results-list__item")
    if items:
        return items
    items = doc.css("li.o-chart-results-list-row, ul.o-chart-results-list-row > li")
    if items:
        return items
    return doc.css("li")


def _text_or_none(node: Optional[HTMLParser]) -> str:
    return _norm(node.text()) if node else ""


def _find_metric_value(item: HTMLParser, labels: List[str]) -> Optional[str]:
    """
    Busca valores tipo 'Last Week', 'Peak Pos.', 'Weeks on Chart'
    Devuelve string con número si lo encuentra, o None si no está.
    """
    for lab in item.css("span.c-label, span"):
        txt = _norm(lab.text()).lower()
        for kw in labels:
            if kw in txt:
                # Intentar número en el mismo texto
                nums = re.findall(r"\d+", txt)
                if nums:
                    return nums[-1]
                # o en hermano inmediato
                sib = lab.next
                if sib:
                    t = _norm(sib.text())
                    if t and re.search(r"\d+", t):
                        return re.findall(r"\d+", t)[-1]
    return None


def _first_href(*nodes: Optional[HTMLParser]) -> str:
    for n in nodes:
        if n and n.attributes.get("href"):
            return n.attributes["href"]
    return ""


def _parse_song_item(item: HTMLParser) -> Dict[str, str]:
    title_node = item.css_first("h3.c-title") or item.css_first("h3")
    title = _text_or_none(title_node)

    # artista: preferir link a /artist/
    a_artist = item.css_first('a[href*="/artist/"]')
    artist = _text_or_none(a_artist)
    if not artist:
        # fallback muy conservador
        for lbl in item.css("span.c-label, span"):
            t = _norm(lbl.text())
            if t and len(t) < 120 and "billboard" not in t.lower():
                if t.lower() not in {"new", "re-entry", "last", "week", "peak", "weeks"}:
                    artist = t
                    break

    # URL informativa
    bb_url = _first_href(
        item.css_first('a[href^="/song/"]'),
        item.css_first('a[href^="/music/"]'),
        item.css_first('a[href*="/artist/"]'),
    )

    row = {
        "title": title,
        "artist": artist,
        "billboard_url": bb_url,
    }

    # métricas (opcionales: solo si se detectan confiables)
    last_week = _find_metric_value(item, ["last week"])
    peak = _find_metric_value(item, ["peak"])
    weeks = _find_metric_value(item, ["weeks"])
    if last_week is not None:
        row["last_week"] = last_week
    if peak is not None:
        row["peak"] = peak
    if weeks is not None:
        row["weeks"] = weeks

    return row


def _parse_artist_item(item: HTMLParser) -> Dict[str, str]:
    a = item.css_first('a[href*="/artist/"]')
    artist = _text_or_none(a) if a else _text_or_none(item.css_first("h3.c-title"))
    bb_url = a.attributes.get("href", "") if a else ""
    row = {
        "artist": artist,
        "billboard_url": bb_url,
    }
    last_week = _find_metric_value(item, ["last week"])
    peak = _find_metric_value(item, ["peak"])
    weeks = _find_metric_value(item, ["weeks"])
    if last_week is not None:
        row["last_week"] = last_week
    if peak is not None:
        row["peak"] = peak
    if weeks is not None:
        row["weeks"] = weeks
    return row


def _parse_album_item(item: HTMLParser) -> Dict[str, str]:
    title = _text_or_none(item.css_first("h3.c-title")) or _text_or_none(item.css_first("h3"))
    a_artist = item.css_first('a[href*="/artist/"]')
    artist = _text_or_none(a_artist)
    bb_url = _first_href(
        item.css_first('a[href^="/music/"]'),
        a_artist
    )
    row = {
        "album_title": title,
        "artist": artist,
        "billboard_url": bb_url,
    }
    last_week = _find_metric_value(item, ["last week"])
    peak = _find_metric_value(item, ["peak"])
    weeks = _find_metric_value(item, ["weeks"])
    if last_week is not None:
        row["last_week"] = last_week
    if peak is not None:
        row["peak"] = peak
    if weeks is not None:
        row["weeks"] = weeks
    return row


def _detect_kind_from_slug(slug: str) -> str:
    s = slug.lower()
    if any(k in s for k in ["hot-", "global", "streaming", "radio", "digital", "songs"]):
        return "song"
    if any(k in s for k in ["billboard-200", "album", "albums", "vinyl", "soundtracks"]):
        return "album"
    if "artist" in s:
        return "artist"
    # default musical
    return "song"


def _extract_header(doc: HTMLParser) -> Tuple[str, Optional[str]]:
    """
    Devuelve (chart_name, week_date) si está disponible.
    week_date va en formato 'Month DD, YYYY' tal como aparece en Billboard.
    """
    # título de chart
    title = ""
    h1 = doc.css_first("h1.c-title") or doc.css_first("h1")
    if h1:
        title = _text_or_none(h1)
    if not title:
        # otro posible lugar
        head = doc.css_first("header") or doc.css_first("div.lrv-a-wrapper")
        if head:
            t = head.css_first("h1") or head.css_first("h2")
            title = _text_or_none(t)

    # fecha (semana)
    text = doc.text() or ""
    m = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}",
        text
    )
    week = m.group(0) if m else None
    return title, week


def get_chart(chart_slug: str, date: Optional[str] = None, force_refresh: bool = False) -> Dict[str, object]:
    """
    Scrapea una chart musical por 'slug' (ej: 'hot-100', 'streaming-songs', 'billboard-200', 'artist-100').
    Opcionalmente se puede pasar 'date' (YYYY-MM-DD) para una semana específica.
    Retorna dict:
    {
      "chart_slug": str,
      "chart_name": str,
      "week": Optional[str],     # ej: "October 26, 2025"
      "items": [ { rank, ... } ] # según tipo: songs/albums/artists
    }
    """
    slug = chart_slug.strip().lower().rstrip("/")
    if slug not in MUSIC_SLUG_ALLOWLIST:
        raise ValueError(f"Chart no permitida (solo música): {slug}")

    cache_key = f"chart::{slug}::{date or 'latest'}"
    now = time.time()

    if (not force_refresh) and cache_key in _CACHE:
        entry = _CACHE[cache_key]
        if now - entry["ts"] < TTL_SECONDS:
            return entry["data"]  # type: ignore

    url = f"{BASE_URL}{slug}/"
    if date:
        url = f"{url}{date}/"  # formateo típico de semana específica

    html = _get_html(url)
    doc = HTMLParser(html)

    chart_name, week = _extract_header(doc)
    kind = _detect_kind_from_slug(slug)

    items_nodes = _extract_items_generic(doc)
    parsed: List[Dict[str, str]] = []

    for it in items_nodes:
        if kind == "song":
            row = _parse_song_item(it)
            if row.get("title") and row.get("artist"):
                parsed.append(row)
        elif kind == "album":
            row = _parse_album_item(it)
            if row.get("album_title") and row.get("artist"):
                parsed.append(row)
        else:
            row = _parse_artist_item(it)
            if row.get("artist"):
                parsed.append(row)

        if len(parsed) >= 120:
            break

    # rank + top 100
    out_items: List[Dict[str, str]] = []
    for i, row in enumerate(parsed[:100]):
        row = {**row}
        row["rank"] = i + 1
        out_items.append(row)

    payload: Dict[str, object] = {
        "chart_slug": slug,
        "chart_name": chart_name or slug.replace("-", " ").title(),
        "week": week,
        "items": out_items,
    }

    _CACHE[cache_key] = {"ts": now, "data": payload}
    return payload


def get_artist_100(force_refresh: bool = False) -> Dict[str, object]:
    return get_chart("artist-100", force_refresh=force_refresh)


if __name__ == "__main__":
    # Uso:
    #   python -m services.billboard_scraper hot-100
    #   python -m services.billboard_scraper billboard-200
    #   python -m services.billboard_scraper global-200 2025-10-25
    slug = sys.argv[1] if len(sys.argv) > 1 else "artist-100"
    date = sys.argv[2] if len(sys.argv) > 2 else None
    data = get_chart(slug, date=date, force_refresh=True)

    # Salida simple legible (puede integrarse a tu API devolviendo 'data' como JSON)
    print(f"# {data['chart_name']} — Week: {data.get('week') or 'latest'}")
    for item in data["items"]:  # type: ignore
        r = item["rank"]
        if "title" in item:       # songs
            print(f"{r:>3}. {item['title']} — {item['artist']}")
        elif "album_title" in item:  # albums
            print(f"{r:>3}. {item['album_title']} — {item['artist']}")
        else:                     # artists
            print(f"{r:>3}. {item['artist']}")