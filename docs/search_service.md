# services/search_service.py

## Objetivo
Orquestar la búsqueda: consulta a InnerTube/ytmusicapi, parseo de “artist card”, resultados generales (songs/albums) y cache.

## Funciones (API pública)

### build_search_payload(
    query: str,
    artist: dict | None,
    artist_songs: list,
    artist_albums: list,
    general: dict,
) -> dict
Función pura. Construye el payload final:
- query
- artist
- artistSongs
- artistAlbums
- search (general)

### get_warm_ids(result: dict) -> list[str]
Extrae `videoId` para warming:
- Siempre toma `artistSongs[*].videoId`
- Si NO hay artist card, también toma `search.songs[*].videoId`
- Dedup + límite 24

### search(query: str, use_cache: bool = True) -> dict
Orquesta principal:
1) cache key: `query.lower()[:100]`
2) cache (CacheType.SEARCH)
3) fetch: `yt = _ytm()` y `response = yt.search(query)`
4) parse:
   - artist: parse_artist_card_info
   - artistSongs: parse_artist_card_songs (con enrich_metadata, strict_atv)
   - artistAlbums: parse_artist_card_albums
5) general:
   - si hay artist => albums 10, songs 0
   - si no hay artist => songs 10 + albums 10 (con enrich_metadata)
6) build_search_payload + cache + return

Errores:
- exception => `{ "query": query, "error": "<detail>" }`