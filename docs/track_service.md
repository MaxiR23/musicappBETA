# services/track_service.py

## Objetivo
Lógica de tracks: normalización de items, lyrics, related y upnext, con cache legacy (TTL por tipo).

## Constantes
- LYRICS_TTL = 12h
- RELATED_TTL = 12h
- UPNEXT_TTL = 6h
- EXCLUDED_RELATED_SECTIONS: secciones a filtrar en related

## Funciones (helpers)

### duration_to_seconds(d: str | None) -> int | None
Convierte "mm:ss" o "hh:mm:ss" a segundos. Si no parsea, devuelve None.

### best_thumb_url(track: dict) -> str | None
Devuelve la mejor URL de thumbnail soportando:
- string directo
- dict {url}
- list (elige la última con url válida)

### normalize_track_item(track: dict) -> dict
Normaliza un track a un formato consistente:
- id (videoId o id)
- title
- artist_name / artist_id (con fallbacks desde artists/author)
- artist_ids + artists (lista original)
- album_id / album_name (desde album o campos planos)
- thumbnail (best_thumb_url)
- duration + duration_seconds (desde lengthSeconds o parse de duration)

## Funciones (API pública)

### get_lyrics(video_id: str) -> dict
Cache key: `lyrics:<video_id>`
- Usa ytmusicapi: get_watch_playlist(videoId=...)
- Obtiene browse_id desde wp["lyrics"]
- Si no hay browse_id => {ok: False, reason: "no_lyrics"} cache corto (5 min)
- Si hay => yt.get_lyrics(browse_id) y devuelve:
  - ok: True
  - lyrics
  - source
- Errores => {ok: False, reason: "error", detail: ...}

### get_related(video_id: str) -> dict
Cache key: `related:<video_id>`
- Usa ytmusicapi: get_watch_playlist(videoId=...)
- Obtiene browse_id desde watch["related"]
- Llama yt.get_song_related(browse_id)
- Si devuelve lista de secciones, filtra títulos en EXCLUDED_RELATED_SECTIONS
- Devuelve:
  - ok: True
  - related: <data>
- Fallos comunes cacheados corto (5 min):
  - no_watch_playlist
  - no_browse_id
- Errores => ok False con cache 1 min

### get_related_raw(video_id: str) -> dict
Debug: related sin filtros ni cache legacy.
Devuelve info de diagnóstico (browseId, watch_related_field, related_raw, etc.)

### get_upnext(video_id: str) -> dict
Cache key: `upnext:<video_id>`
- Usa ytmusicapi:
  - yt.get_song(video_id) para videoDetails
  - yt.get_watch_playlist(videoId=...) para tracks/autoplay
- Normaliza current y upNext con normalize_track_item
- Devuelve:
  - ok: True
  - current
  - upNext
  - autoplay
- Fallos comunes cacheados corto (5 min):
  - no_tracks
- Errores => ok False con cache 1 min