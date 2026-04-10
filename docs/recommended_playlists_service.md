# services/recommended_playlists_service.py

## Objetivo
Recomendar playlists de género basadas en el historial de reproducción del usuario (últimos 45 días).
Cruza artistas más escuchados con tracks en genre_playlists y rankea por cantidad de matches.

## Config relevante
- Cache: CacheType.RECOMMENDED_PLAYLISTS (schedule MONDAY, TTL 7 días)
- RPC: recommend_playlists_by_history (Supabase, SECURITY DEFINER)
- Parámetros default: p_days=45, p_limit=5

## Funciones (API pública)

### get_recommended_playlists(user_id: str, days: int = 45, limit: int = 5) -> list
Devuelve una lista de playlists recomendadas, cada una con:
- playlist_id: uuid
- playlist_title: str
- total_tracks: int
- matching_tracks: int (tracks del usuario encontrados en la playlist)
- matching_artists: int (artistas del usuario encontrados en la playlist)
- thumbnails: list[str] (primeras 4 URLs para mosaico 2x2)

Internamente:
- cache en memoria por user_id (suffix)
- llama al RPC recommend_playlists_by_history via supabase_service (service-role)

## RPC: recommend_playlists_by_history

### Lógica
1. top_artists: top 20 artistas por play_count en play_events (últimos N días)
2. matched_tracks: cruza artistas con tracks en genre_playlist_tracks
3. ranked: agrupa por playlist, ordena por matching_artists DESC, matching_tracks DESC
4. thumbs: primeras 4 thumbnails por playlist (position <= 4)

## Ruta

### GET /feed/recommended-playlists
- Auth: Bearer (get_current_user_id via Depends)
- Cache: manejado por el service
- Response: { ok: true, playlists: [...] }

## Frontend

### RecommendedPlaylistsSection
- Ubicación: components/features/home/RecommendedPlaylistsSection.tsx
- Usa PlaylistCover para mosaico 2x2
- Usa HorizontalScrollSection con renderItem custom
- Navega a /(tabs)/home/genre-playlist/[id]
- i18n: sections.recommendedPlaylists.title / artistsMatch