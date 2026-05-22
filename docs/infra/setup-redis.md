# Setup de Redis en el servidor

## Objetivo
Instalar y configurar Redis como storage de versiones manuales de cache.
Requerido por services/cache_config.py.

## Pasos de instalacion

### 1. Instalar Redis
sudo apt update
sudo apt install redis-server -y

### 2. Generar password fuerte
openssl rand -base64 32
Copiar el output para los siguientes pasos.

### 3. Agregar password al config de Redis
echo 'requirepass TU_PASSWORD' | sudo tee -a /etc/redis/redis.conf > /dev/null
sudo systemctl restart redis-server

### 4. Verificar
redis-cli -a TU_PASSWORD ping
Esperado: `PONG`.

Sin password (debe fallar):
redis-cli ping
Esperado: `(error) NOAUTH Authentication required.`

## Seguridad
- Por default, Redis bindea a 127.0.0.1 (solo localhost). No exponer a internet.
- El password vive en /etc/redis/redis.conf (permisos 640, root:redis).

## Variables de entorno en el .env del backend
REDIS_PASSWORD=el_password_generado
REDIS_HOST y REDIS_PORT no necesitan setearse si se usan los defaults
(localhost:6379).

IMPORTANTE: en el .env, el valor NO debe llevar comillas.
Correcto:   REDIS_PASSWORD=abc123xyz
Incorrecto: REDIS_PASSWORD="abc123xyz"
(El motivo se explica en la seccion siguiente.)

## Carga del .env en el servicio (systemd) -- CRITICO

### El problema
systemd NO lee el .env automaticamente. Aunque el archivo .env exista en
el WorkingDirectory, el proceso de la app arranca SIN esas variables a
menos que se lo indiquemos explicitamente. Sintoma tipico:

- La app arranca bien (`Application startup complete`, `Uvicorn running`).
- redis-cli con el password del .env responde `PONG` (Redis esta sano).
- Pero en los logs aparece, en CADA request:
    Error leyendo version manual de Redis (...): Authentication required.
- Como el fallback es graceful, la app no crashea: simplemente nunca
  usa las versiones manuales de cache. "Anda local pero en el server no".

La causa: la app recibe REDIS_PASSWORD vacio porque systemd no le paso
el .env.

### La solucion: EnvironmentFile en el override
Agregar la directiva EnvironmentFile al override de systemd, apuntando
al .env del backend.

1. Editar el override:
   sudo systemctl edit <SERVICIO>

2. El bloque [Service] debe quedar asi (la linea de PATH puede ya existir;
   se agrega la de EnvironmentFile):
       [Service]
       Environment="PATH=..."
       EnvironmentFile=<RUTA_DEL_PROYECTO>/.env

3. Recargar la config de systemd y reiniciar:
   sudo systemctl daemon-reload
   sudo systemctl restart <SERVICIO>

### Caveat de las comillas
systemd parsea el EnvironmentFile distinto a una shell. Si un valor en el
.env esta entre comillas, systemd las toma como parte LITERAL del valor.
Es decir, REDIS_PASSWORD="abc" hace que el password real sea `"abc"`
(con comillas incluidas) y Redis sigue rechazando con Authentication
required. Por eso los valores del .env van sin comillas.

### Verificacion post-restart
Revisar los logs recientes:
   journalctl -u <SERVICIO> -n 30 --no-pager

Senales de exito:
- Ya NO aparece ningun `Authentication required`.
- Los requests responden 200 OK, incluido el endpoint que toca la logica
  de versiones migrada a Redis.

## Persistencia
Redis con configuracion default hace RDB snapshots periodicos a disco.
Para el volumen de keys que maneja cache_config (~10-30 strings cortos),
el archivo de snapshot es despreciable (< 1KB). No es necesario activar AOF.

## Servicio Redis (systemd)
El paquete redis-server registra automaticamente el servicio en systemd
con auto-start al boot. Comandos utiles:
sudo systemctl status redis-server
sudo systemctl restart redis-server
sudo systemctl stop redis-server

## Migracion inicial de overrides existentes
Cuando se hace la migracion de un sistema que ya tenia overrides en un
cache_versions.json local, hay que volcarlos a Redis ANTES de eliminar
el JSON, sino se pierden.

Esto se hace con un script one-time standalone (no dependiente de
redis_client.py) que:
1. Carga REDIS_PASSWORD desde el .env.
2. Lee el cache_versions.json existente.
3. Setea cada entry en Redis con la key `cache:manual:<cache_type>`.

Despues de la migracion y del deploy del codigo nuevo (que elimina el JSON
del filesystem), la app arranca leyendo de Redis y los overrides estan
preservados.

## Checklist de troubleshooting (orden recomendado)
Si "anda local pero en el server no", verificar en este orden:
1. Servicio activo:           sudo systemctl status <SERVICIO>
2. La app responde local:     curl -v http://localhost:<PUERTO>/docs
3. Redis responde:            export $(grep REDIS_PASSWORD .env) && redis-cli -a "$REDIS_PASSWORD" ping
4. Logs sin errores de auth:  journalctl -u <SERVICIO> -f
5. systemd carga el .env:     cat /etc/systemd/system/<SERVICIO>.service.d/override.conf
   (debe tener la linea EnvironmentFile)