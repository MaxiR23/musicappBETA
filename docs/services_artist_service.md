# services/artist_service.py

## Objetivo
Orquestación del payload de artista: browse + artist_data en paralelo, parsing, armado de payload, cache, eventos y new releases.

## Funciones (API pública)

### parse_header(raw: dict) -> dict
Extrae header desde browse response.
Devuelve:
- name: str | None
- description: str
- thumbnails: list

### parse_contents(raw: dict) -> list
Extrae la lista de secciones (contents) desde browse response.

### find_albums_section(contents: list) -> dict | None
Busca la sección "albums" dentro de contents.

### find_singles_section(contents: list) -> dict | None
Busca la sección "singles" / "EPs" dentro de contents.

### get_top_songs(artist_id: str) -> list
Trae top songs usando music_client.get_artist + parse_top_songs_v2.

### get_albums(artist_id: str, limit: int = 10) -> list
Trae albums usando browse + parse_albums.
Nota: hace browse propio.

### get_singles(artist_id: str, limit: int = 10) -> list
Trae singles/EP usando browse + parse_singles_eps.
Nota: hace browse propio.

### get_related(artist_id: str) -> list
Trae artistas relacionados usando browse + parse_related_artists.
Nota: hace browse propio.

### get_more_from_artist(artist_id: str, exclude_album_id: str | None = None, limit: int = 10) -> list
Trae “más del artista” usando get_albums y filtrando un album a excluir.

### build_artist_payload(
    artist_id: str,
    header: dict,
    top_songs: list,
    albums: list,
    singles: list,
    related: list,
    has_more: dict,
    events: list | None = None,
    new_releases: list | None = None,
) -> dict
Función pura. Arma el payload final del artista.
Elimina keys vacías (albums, singles_eps, top_songs) para mantener respuesta limpia.

### get_artist(artist_id: str, use_cache: bool = True) -> dict
Orquesta principal:
1) cache (CacheType.ARTIST)
2) fetch paralelo:
   - music_client.browse(artist_id)
   - music_client.get_artist(artist_id)
3) parse sections (albums/singles/related/header)
4) top_songs con parse_top_songs_v2
5) has_more calculado desde artist_data (albums/singles)
6) events: get_events_cached_only + schedule_events_refresh si vacío
7) new releases: list_new_releases_for_artist (best-effort)
8) cachea y devuelve payload

Errores:
- si raw vacío => {"id": artist_id, "error": "not_found"}
- exceptions => {"id": artist_id, "error": "<detail>"}

### get_all_albums(artist_id: str, use_cache: bool = True) -> dict
Devuelve TODOS los albums del artista:
- usa CacheType.ARTIST_ALBUMS
- si artist_data trae browseId/params => music_client.get_artist_albums
- sino fallback a results
Devuelve:
- artist_id
- total
- albums: [{id, title, year, thumbnails}]

### get_all_singles(artist_id: str, use_cache: bool = True) -> dict
Devuelve TODOS los singles/EPs del artista enriquecidos:
- usa CacheType.ARTIST_SINGLES
- fetch lista base (browseId/params o results)
- por cada item, hace music_client.get_album(browse_id) para enriquecer type/trackCount
- paralelo con ThreadPoolExecutor
Devuelve:
- artist_id
- total
- singles: [{id, title, type, year, thumbnails, trackCount}]