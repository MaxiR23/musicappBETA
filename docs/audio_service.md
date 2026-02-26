# services/audio_service.py

## Objetivo
Resolver una URL directa de audio para un videoId (YouTube) y streamearla con soporte de Range.
Incluye warming (prefetch) opcional.

## Config relevante
- WARM_ENABLED: habilita/deshabilita warming
- URL_TTL: TTL base si no se puede derivar de querystring
- _WARM_BURST: cantidad máxima por tanda
- _WARM_DEDUP_TTL: anti-dedup temporal

## Funciones (API pública)

### get_audio_info(video_id: str) -> dict
Devuelve un dict con:
- info: dict
- direct_url: str
- client: "pytubefix" | "yt-dlp"
- ts: float
- ttl: int

Internamente:
- cache en memoria por video_id
- extracción: pytubefix primero, fallback yt-dlp

### stream_from_url(url: str, range_header: str | None) -> StreamingResponse
Hace proxy streaming desde el origin:
- setea headers esperados por players (Accept-Ranges, Content-Range, Content-Length)
- respeta Range si el origin lo soporta
- intenta un resume 1 vez si se corta la conexión (ChunkedEncodingError/ConnectionError/ReadTimeout)

### schedule_warm(ids: list[str]) -> None
Si WARM_ENABLED=True:
- dedup por id + TTL corto (_WARM_DEDUP_TTL)
- ejecuta warm en ThreadPoolExecutor
- warm hace:
  - get_audio_info
  - probe de la URL (Range bytes=0-1)

### get_warm_burst() -> int
Devuelve el burst configurado (_WARM_BURST).