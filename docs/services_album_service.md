# services/album_service.py

## Objetivo
Orquestación del payload de álbum: browse + parsing info, tracks por audioPlaylistId, “more from artist”, eventos, cache.

## Funciones (API pública)

### extract_artist_name(info: dict) -> str | None
Obtiene nombre de artista desde info:
- artistName
- artists[0].name
- artist
- subtitle
Además limpia " • " si viene "Artist • Something".

### build_album_payload(
    album_id: str,
    raw: dict,
    info: dict,
    tracks: list | None = None,
    more_from_artist: list | None = None,
    events: list | None = None,
) -> dict
Función pura. Arma payload final del álbum:
- id
- info
- tracks
- otherVersions (parse_album_other_versions)
- moreFromArtist
- upcomingEvents
- releasesForYou (parse_album_releases_for_you)

### get_album_tracks(audio_playlist_id: str) -> list
Devuelve tracks parseando audio_playlist_id vía parse_tracks_from_audio_playlist.
Si no hay id => [].

### get_album(album_id: str, use_cache: bool = True) -> dict
Orquesta principal:
1) cache (CacheType.ALBUM)
2) raw = music_client.browse(album_id)
3) info = parse_album_info(raw)
4) fetch paralelo:
   - tracks (audioPlaylistId)
   - more_from_artist (artistId, excluyendo este album)
5) events: get_events_cached_only(artist_name) + schedule_events_refresh si vacío
6) build_album_payload + cache + return

Errores:
- raw vacío => {"id": album_id, "error": "not_found"}
- exceptions => {"id": album_id, "error": "<detail>"}