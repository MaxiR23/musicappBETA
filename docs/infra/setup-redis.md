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

## Persistencia
Redis con configuracion default hace RDB snapshots periodicos a disco.
Para el volumen de keys que maneja cache_config (~10-30 strings cortos),
el archivo de snapshot es despreciable (< 1KB). No es necesario activar AOF.

## Servicio (systemd)
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