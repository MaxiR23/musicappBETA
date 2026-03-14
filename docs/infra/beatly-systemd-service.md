# Correr el backend en Google Cloud VM con systemd

## Contexto

Cuando corrés tu servidor FastAPI desde la consola SSH de Google Cloud, el proceso **muere al cerrar la terminal**. La solución es registrarlo como un **servicio de systemd**, que lo mantiene vivo, lo reinicia si crashea y lo arranca automáticamente cuando la VM bootea.

> SEE: [systemd — Service unit documentation](https://www.freedesktop.org/software/systemd/man/systemd.service.html)

---

## Crear el archivo del servicio

```bash
sudo tee /etc/systemd/system/beatly.service << 'SVCEOF'
[Unit]
Description=Beatly API
After=network.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
User=TU_USUARIO
WorkingDirectory=/home/TU_USUARIO/TU_PROYECTO
ExecStart=/home/TU_USUARIO/TU_PROYECTO/venv/bin/python3 -m uvicorn app:app --host 0.0.0.0 --port TU_PUERTO
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF
```

---

## Qué hace cada sección

### `[Unit]` — metadatos y condiciones de arranque

| Clave | Qué hace |
|---|---|
| `Description` | Nombre legible, aparece en `systemctl status` |
| `After=network.target` | Espera a que la red esté lista antes de arrancar |
| `StartLimitIntervalSec=60` | Ventana de tiempo para contar intentos fallidos |
| `StartLimitBurst=5` | Máximo de 5 crasheos en 60 segundos antes de darse por vencido |

### `[Service]` — cómo correr la app

| Clave | Qué hace |
|---|---|
| `User` | Corre con tu usuario, no como root (más seguro) |
| `WorkingDirectory` | Equivale al `cd musicappBETA` que hacías a mano |
| `ExecStart` | El comando exacto para arrancar, usando el Python del venv |
| `Restart=always` | Si se cae por cualquier motivo, lo reinicia |
| `RestartSec=5` | Espera 5 segundos antes de reiniciar (evita bucles infinitos) |

### `[Install]` — cuándo arrancar

| Clave | Qué hace |
|---|---|
| `WantedBy=multi-user.target` | Arranca automáticamente cuando la VM bootea en modo normal |

---

## Lógica de reinicio

```
App se cae → espera 5 seg → reinicia → app vuelve

Si crashea 5 veces en menos de 60 segundos:
→ systemd se da por vencido → app queda caída
→ Revisá los logs para encontrar el problema
```

Esto reemplaza lo que hacías a mano:

```bash
cd TU_PROYECTO && source venv/bin/activate && python3 -m uvicorn app:app --host 0.0.0.0 --port TU_PUERTO
```

> SEE: [systemd — Restart options](https://www.freedesktop.org/software/systemd/man/systemd.service.html#Restart=)

---

## Activar y arrancar el servicio

```bash
sudo systemctl daemon-reload   # recarga la configuración de systemd
sudo systemctl enable beatly   # arranca automáticamente con la VM
sudo systemctl start beatly    # arranca ahora
```

Verificar que esté corriendo:

```bash
sudo systemctl status beatly
```

Output esperado:

```
● beatly.service - Beatly API
     Loaded: loaded (/etc/systemd/system/beatly.service; enabled; preset: enabled)
     Active: active (running) since Sat 2026-03-14 06:24:16 UTC; 31s ago
   Main PID: 113837 (python3)
     Memory: 68.7M
```

La línea clave es `Active: active (running)` — si ves eso, el servicio está corriendo correctamente.

---

## Comandos útiles del día a día

| Comando | Qué hace |
|---|---|
| `sudo systemctl status beatly` | Ver estado actual |
| `sudo systemctl restart beatly` | Reiniciar (usar después de cambios en el código) |
| `sudo systemctl stop beatly` | Detener el servicio |
| `sudo systemctl start beatly` | Arrancar el servicio |
| `sudo journalctl -u beatly -f` | Ver logs en tiempo real |
| `sudo journalctl -u beatly -n 50` | Ver las últimas 50 líneas de logs |

> SEE: [systemctl — Command reference](https://www.freedesktop.org/software/systemd/man/systemctl.html)
> SEE: [journalctl — Viewing logs](https://www.freedesktop.org/software/systemd/man/journalctl.html)

---

## Flujo completo después de un cambio de código

```bash
# 1. Hacé tus cambios en el código
# 2. Reiniciá el servicio
sudo systemctl restart beatly

# 3. Verificá que arrancó bien
sudo systemctl status beatly
```

---

## Estructura de archivos relevante

```
/home/TU_USUARIO/
└── TU_PROYECTO/
    ├── app.py              ← entry point de FastAPI
    ├── venv/
    │   └── bin/
    │       └── python3     ← Python del entorno virtual
    └── ...

/etc/systemd/system/
└── beatly.service          ← el servicio que creamos
```

> SEE: [Google Cloud — Connecting to VMs](https://cloud.google.com/compute/docs/connect/standard-ssh)