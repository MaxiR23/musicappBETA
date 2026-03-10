# Route Testing — Backend de Beatly

## Qué hicimos

Escribimos **route tests** (API contract tests) para las rutas del backend. Cubrimos el contrato HTTP de cada endpoint: status codes, query params, validaciones, y que los servicios sean llamados con los argumentos correctos.

**Archivos testeados:**

| Archivo | Tests |
|---|---|
| `routes/search.py` | 6 |
| `routes/stats.py` | 13 |
| `routes/tracks.py` | 16 |
| `routes/upcoming_releases.py` | 9 |
| `routes/activity.py` | — |
| `routes/feed.py` | — |
| `routes/genres.py` | — |
| `routes/playlists.py` | — |

---

## Qué tipo de test es este

Los route tests verifican el **contrato HTTP** de cada endpoint:

- Status codes correctos (200, 401, 404, 422, 502)
- Query params y validaciones (ge, le, required)
- Que los servicios sean llamados con los argumentos correctos
- Que los errores del service se traduzcan en respuestas HTTP correctas

**No testean lógica de negocio** — eso es territorio de unit tests.  
**No testean DB real** — eso es territorio de integration tests.

```
Unit tests      → services/     → lógica pura + mocks de DB/APIs
Route tests     → routes/       → contrato HTTP + mocks de services
Integration     → (próximo)     → endpoints completos contra DB real
```

---

## Convención

Cada archivo de ruta tiene su archivo de test espejo:

```
routes/search.py           →  test/routes/test_search_routes.py
routes/stats.py            →  test/routes/test_stats_routes.py
routes/tracks.py           →  test/routes/test_tracks_routes.py
routes/upcoming_releases.py → test/routes/test_upcoming_releases_routes.py
```

---

## Estructura de cada archivo de test

```python
# ════════════════════════════════════════════════════════
# GET /endpoint
# ════════════════════════════════════════════════════════

class TestEndpointName:
    def test_returns_200_on_success(self, client): ...
    def test_returns_404_when_not_found(self, client): ...
    def test_returns_422_on_invalid_param(self, client): ...
    def test_returns_502_on_exception(self, client): ...
    def test_passes_correct_args_to_service(self, client): ...
```

---

## Patrones usados

### App mínima con router aislado

```python
@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/prefix")
    return TestClient(app)
```

Se crea una app mínima solo con el router bajo test. Sin lifespan, sin middleware, sin otros routers.

> Si la ruta tiene `@router.get("")` (path vacío), siempre incluir `prefix` en `include_router`.

### Override de dependencias (Depends)

```python
FAKE_DB = MagicMock()
FAKE_USER_ID = "user-123"

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: FAKE_DB
    app.dependency_overrides[get_current_user_id] = lambda: FAKE_USER_ID
    return TestClient(app)
```

Para testear el caso no autenticado:

```python
@pytest.fixture
def unauthed_client():
    from fastapi import HTTPException
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_id] = lambda: (_ for _ in ()).throw(
        HTTPException(status_code=401, detail="unauthorized")
    )
    return TestClient(app, raise_server_exceptions=False)
```

### Patch de servicios

```python
def test_passes_correct_args_to_service(self, client):
    with patch("routes.stats.get_weekly_summary", return_value=RESULT) as mock:
        client.get("/weekly?include=artists&limit=5")
    mock.assert_called_once_with(FAKE_DB, FAKE_USER_ID, include="artists", limit=5)
```

> Siempre patchear donde se **usa** (`routes.stats.get_weekly_summary`),  
> no donde se **define** (`services.weekly_stats_service.get_weekly_summary`).

### Verificación de status codes

```python
def test_returns_502_on_exception(self, client):
    with patch("routes.stats.get_weekly_summary", side_effect=Exception("db down")):
        r = client.get("/weekly")
    assert r.status_code == 502
    assert r.json()["error"] == "service_unavailable"
    assert r.json()["ok"] is False
```

---

## Qué NO testeamos acá

- Lógica de negocio dentro de los services → unit tests
- DB real / transacciones → integration tests
- Comportamiento del framework (FastAPI, Starlette) en sí mismo

> Los tests de validación de Query params (`ge=1, le=100`) sí los incluimos  
> porque testean que **nosotros configuramos bien el contrato**, no el framework.

---

## Próximo paso

**Integration tests** — testear endpoints completos contra una DB real dentro de una transacción que se hace rollback al final.

> SEE: [pytest — fixtures](https://docs.pytest.org/en/stable/reference/fixtures.html)  
> SEE: [FastAPI — Testing](https://fastapi.tiangolo.com/tutorial/testing/)