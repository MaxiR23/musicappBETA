# Cómo correr los tests

## Requisitos

```bash
pip install pytest pytest-mock
```

> SEE: [pytest — Installation](https://docs.pytest.org/en/stable/getting-started.html)

---

## Correr todos los tests

```powershell
pytest test/ -v
```

## Correr un archivo específico

```powershell
pytest test/services/test_album_service.py -v
```

## Correr una clase específica

```powershell
pytest test/services/test_album_service.py::TestGetAlbum -v
```

## Correr un test específico

```powershell
pytest test/services/test_album_service.py::TestGetAlbum::test_returns_cached_when_available -v
```

> SEE: [pytest — How to invoke](https://docs.pytest.org/en/stable/how-to/usage.html)

---

## Flags útiles

| Flag | Qué hace |
|---|---|
| `-v` | Muestra nombre de cada test |
| `-s` | Muestra `print()` del código durante los tests |
| `-x` | Para al primer fallo |
| `--tb=short` | Traceback resumido en caso de fallo |
| `-k "nombre"` | Corre solo tests que matcheen el string |

Ejemplos:

```powershell
# Ver prints del código (útil para debug)
pytest test/services/test_album_service.py -v -s

# Parar al primer fallo
pytest test/ -x

# Correr solo tests que contengan "cache" en el nombre
pytest test/ -k "cache" -v
```

> SEE: [pytest — Command-line flags](https://docs.pytest.org/en/stable/reference/reference.html#command-line-flags)

---

## Output esperado

```
============================= test session starts =============================
collected 28 items

test/services/test_album_service.py::TestExtractArtistName::test_from_artists_list PASSED
test/services/test_album_service.py::TestExtractArtistName::test_from_artist_name_field PASSED
...
============================== 28 passed in 0.35s =============================
```

Un test **FAILED** muestra exactamente qué valor se esperaba vs qué llegó:

```
E   AssertionError: assert None == 'Radiohead'
E    +  where None = extract_artist_name({})
```

---

## En PowerShell — ver solo las primeras N líneas

`head` no existe en PowerShell. Usar:

```powershell
pytest test/ -v 2>&1 | Select-Object -First 50
```

> SEE: [pytest — Output capturing](https://docs.pytest.org/en/stable/how-to/capture.html)

---

## Estructura de carpetas esperada

```
backend/
├── services/
│   ├── album_service.py
│   └── ...
└── test/
    ├── conftest.py
    └── services/
        ├── test_album_service.py
        └── ...
```

pytest descubre automáticamente los archivos que empiezan con `test_`.

> SEE: [pytest — Test discovery](https://docs.pytest.org/en/stable/explanation/goodpractices.html#test-discovery)