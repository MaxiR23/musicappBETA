# Rate Limiting — Beatly API

## Qué hicimos

Implementamos rate limiting global en el backend usando **slowapi**, limitando a **200 requests por minuto por IP** en todos los endpoints sin tocar ninguna ruta individualmente.

---

## Por qué rate limiting

- Evita que un cliente abusivo o bot consuma todos los recursos del servidor
- Protege los endpoints que llaman a YouTube Music (que tiene sus propios límites)
- Estándar en cualquier API pública o semi-pública

---

## Librería elegida: slowapi

| Opción | Requiere Redis | Complejidad | Uso |
|---|---|---|---|
| **slowapi** | No | Baja | Servidores únicos, proyectos indie/beta |
| fastapi-limiter | Sí | Media | Multi-servidor, alta escala |

Para Beatly en esta etapa, slowapi es la opción correcta — sin infraestructura extra.

---

## Cambios realizados

### 1. Instalación

```bash
pip install slowapi
```

`requirements.txt`:
```
slowapi==0.1.9
```

### 2. Imports en `app.py`

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
```

### 3. Configuración del limiter

```python
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
```

- `key_func=get_remote_address` — identifica clientes por IP
- `default_limits=["200/minute"]` — límite global para todos los endpoints

### 4. Registro en la app

```python
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
add_cors_middleware(app)
app.add_middleware(SlowAPIMiddleware)
```

---

## Comportamiento

- Si una IP supera 200 requests en un minuto → respuesta automática `429 Too Many Requests`
- El contador se reinicia cada minuto
- No requiere ningún cambio en las rutas individuales

---

## Cómo limitar un endpoint específico (referencia futura)

Si en algún momento querés un límite distinto para un endpoint puntual:

```python
from app import limiter

@router.get("/buscar")
@limiter.limit("30/minute")
def buscar(request: Request, q: str):
    ...
```

> `request: Request` es obligatorio cuando se usa `@limiter.limit()` en una ruta específica.

---

## Referencias para estudiar

| Tema | Link |
|---|---|
| slowapi — documentación oficial | https://slowapi.readthedocs.io |
| slowapi — repositorio | https://github.com/laurentS/slowapi |
| Rate limiting — conceptos generales | https://www.cloudflare.com/learning/bots/what-is-rate-limiting |
| HTTP 429 Too Many Requests | https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/429 |
| Límites de YouTube Data API | https://developers.google.com/youtube/v3/getting-started#quota |

---

## Estado

| Item | Estado |
|---|---|
| slowapi instalado | OK |
| Límite global 200/min por IP | OK |
| Middleware registrado | OK |
| Servidor levanta sin errores | OK |