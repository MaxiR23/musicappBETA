# services/redis_client.py

## Objetivo
Centralizar la conexion a Redis para todo el backend con un cliente
singleton lazy. Aisla la configuracion de la conexion del resto del codigo
para que cualquier servicio que necesite Redis lo importe de un solo lugar.

## Config relevante (env vars)
- REDIS_HOST (default: "localhost")
- REDIS_PORT (default: 6379)
- REDIS_PASSWORD (default: None)

## Funciones (API publica)

### get_redis() -> redis.Redis
Devuelve el cliente Redis. La primera llamada crea la conexion;
las siguientes reutilizan la misma instancia (lazy singleton).
- decode_responses=True: devuelve strings, no bytes.
- Lee la config de env vars con defaults razonables para desarrollo local.


---


# services/cache_config.py (seccion: Persistencia de versiones manuales)

## Objetivo
Almacenar los overrides manuales de version de cache en Redis en lugar de
en un archivo JSON local. Esto permite que multiples procesos (servidor,
scripts de mantenimiento, etc.) compartan el mismo estado de invalidacion
y que cada cambio sea atomico.

## Esquema de keys en Redis
Prefijo: `cache:manual:`
Una key por CacheType. Ejemplos:
- cache:manual:new-releases
- cache:manual:artist-albums
- cache:manual:top-tracks
- cache:manual:user-recommendations

Valor: string con la version override (ej: "override-20260521-130000").

## Funciones privadas (helpers de Redis)

### _manual_version_key(cache_type_value: str) -> str
Construye la key completa de Redis para un cache_type dado
(prefija con `cache:manual:`).

### _get_manual_version(cache_type_value: str) -> Optional[str]
Lee la version manual desde Redis. Devuelve None si no existe.
Fallback graceful: si Redis falla, loguea el error y devuelve None
(la app sigue funcionando con la version automatica del schedule).

### _set_manual_version(cache_type_value: str, version: str)
Guarda la version manual en Redis con un SET atomico.
Fallback graceful: loguea error si Redis falla.

### _delete_manual_version(cache_type_value: str)
Borra la version manual de Redis.
Fallback graceful: loguea error si Redis falla.

## Funciones publicas (modificadas)

### set_manual_version(cache_type: CacheType, version: Optional[str] = None)
Fuerza una version manual para invalidar el cache inmediatamente.
- Si `version` es None, genera un timestamp (override-YYYYMMDD-HHMMSS).
- Antes: 5 operaciones de I/O sobre disco (read, parse, modify, serialize, write).
- Ahora: 1 operacion atomica (SET en Redis).

### clear_manual_version(cache_type: CacheType)
Limpia la version manual y devuelve al schedule automatico.
- Ahora: 1 DEL en Redis (en lugar de read-modify-write del JSON).

### get_version(cache_type: CacheType) -> str
Sin cambios en el contrato externo, solo cambia el storage interno:
1. Lee version manual de Redis (_get_manual_version). Si existe, retorna.
2. Si no, calcula version automatica segun el CacheSchedule.

## Notas

- El archivo cache_versions.json fue eliminado del repositorio
  y agregado a .gitignore. El estado runtime ahora vive solo en Redis.
- Dependencia nueva: redis (cliente Python).
- Compatibilidad: el contrato publico de set_manual_version,
  clear_manual_version y get_version no cambio, asi que el resto
  del codigo que los usa no necesita modificaciones.