# Unit Testing — Backend de Beatly

## Qué hicimos

Escribimos la suite de **unit tests** para los servicios del backend. Cubrimos lógica pura (funciones sin IO) y funciones con dependencias externas (DB, cache, APIs) usando mocks.

**Archivos testeados:**

| Archivo | Tests |
|---|---|
| `services/album_service.py` | 28 |
| `services/artist_service.py` | ~65 |
| `services/audio_service.py` | ~60 |
| `services/auth_utils.py` | 23 |
| `services/events_service.py` | ~40 |
| `services/feed_repo.py` | ~55 |
| `services/feed_fetcher.py` | ~55 |
| `services/genre_repo.py` | ~65 |
| `services/monthly_stats_service.py` | ~50 |
| `services/search_service.py` | ~45 |
| `services/track_service.py` | ~75 |
| `services/weekly_stats_service.py` | ~45 |

---

## Convención

Cada archivo de producción tiene su archivo de test espejo:

```
services/album_service.py  →  test/services/test_album_service.py
services/artist_service.py →  test/services/test_artist_service.py
...
```

> SEE: [pytest — Good Integration Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html)

---

## Estructura de cada archivo de test

```python
# ════════════════════════════════════════════════════════
# FUNCIONES PURAS  (sin mocks, input/output directo)
# ════════════════════════════════════════════════════════

class TestNombreFuncion:
    def test_caso_normal(self): ...
    def test_edge_case(self): ...

# ════════════════════════════════════════════════════════
# IO (funciones con dependencias externas → mocks)
# ════════════════════════════════════════════════════════

class TestGetAlbum:
    def test_returns_cached_when_available(self): ...
    def test_fetches_on_cache_miss(self): ...
```

Las funciones puras se testean directamente. Las funciones IO usan `unittest.mock.patch` para aislar DB, cache y APIs externas.

> SEE: [unittest.mock — Official Docs](https://docs.python.org/3/library/unittest.mock.html)  
> SEE: [pytest — How to monkeypatch/mock](https://docs.pytest.org/en/stable/how-to/monkeypatch.html)

---

## Patrones usados

### Mock de DB (cadena fluente)

```python
def make_db():
    db = MagicMock()
    table = MagicMock()
    db.table.return_value = table
    table.select.return_value = table
    table.eq.return_value = table
    table.execute.return_value = res
    return db, table, res
```

Cada método retorna el mismo mock para soportar encadenamiento tipo Supabase.

### Patch de dependencias externas

```python
with patch("services.album_service.get_cached", return_value=None), \
     patch("services.album_service.music_client.browse", return_value=raw), \
     patch("services.album_service.set_cached") as mock_set:
    result = get_album("a1")

mock_set.assert_called_once()
```

> SEE: [unittest.mock — patch](https://docs.python.org/3/library/unittest.mock.html#unittest.mock.patch)

### Verificación de side effects

```python
def test_returns_error_on_exception(self):
    with patch("services.album_service.music_client.browse",
               side_effect=Exception("network error")):
        result = get_album("a1")
    assert "error" in result
```

---

## Qué NO testeamos acá (integration)

Las funciones que hacen HTTP real a servicios externos **no se testean en unit tests**. Eso es territorio de integration tests.

Ejemplos excluidos: funciones de fetch que realizan requests reales a APIs de terceros.

> SEE: [pytest — Testing types](https://docs.pytest.org/en/stable/explanation/anatomy.html)

---

## Próximo paso

**Integration tests** — testear endpoints completos contra una DB real dentro de una transacción que se hace rollback al final, al estilo del fixture PHP de referencia del proyecto.

> SEE: [pytest — fixtures](https://docs.pytest.org/en/stable/reference/fixtures.html)