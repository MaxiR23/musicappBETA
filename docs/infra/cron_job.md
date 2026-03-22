# Cron Jobs — Beatly Backend

## Overview

Scripts automáticos que corren en la VM de GCP (Compute Engine) para tareas que no pueden depender de que un usuario visite la app.

Actualmente hay un solo cron configurado: `check_releases.py`.

---

## Servidor

- **VM:** GCP Compute Engine (e2-medium, São Paulo)
- **OS:** Ubuntu 24
- **Proyecto:** `/home/stephencurrygt30/musicappBETA`
- **Python:** `/home/stephencurrygt30/musicappBETA/venv/bin/python`
- **Log:** `/var/log/check_releases.log`

---

## Crontab actual

```
0 22 * * * cd /home/stephencurrygt30/musicappBETA && /home/stephencurrygt30/musicappBETA/venv/bin/python scripts/check_releases.py >> /var/log/check_releases.log 2>&1
0 3  * * * cd /home/stephencurrygt30/musicappBETA && /home/stephencurrygt30/musicappBETA/venv/bin/python scripts/check_releases.py --fallback >> /var/log/check_releases.log 2>&1
```

### Formato crontab

```
m  h  dom  mon  dow  command
0  22 *    *    *    = todos los días a las 22:00
0  3  *    *    *    = todos los días a las 03:00
```

---

## check_releases.py

Confirma o posterga upcoming releases del día.

### Modo normal (22:00)

```bash
python scripts/check_releases.py
```

1. Consulta `get_todays_pending()` — releases con `release_date = hoy` y `status = pending`
2. Si no hay → sale inmediatamente. Cero trabajo.
3. Por cada release: chequea si el album ya está disponible comparando con los albums del artista
4. Si está → `mark_as_released` + invalida cachés
5. Delay de 3 segundos entre cada call externo para no saturar
6. Los que no salieron quedan pending para el fallback de las 03:00

### Modo fallback (03:00)

```bash
python scripts/check_releases.py --fallback
```

1. Consulta `get_todays_pending()` — lo que sigue pending de hoy
2. Si no hay → sale inmediatamente
3. Los que quedan → `mark_as_postponed` (no salió, se asume postergado)
4. Invalida cachés
5. Cero calls externos — solo updates a la DB

### Costo operativo

| Escenario | Calls externos | Queries DB |
|---|---|---|
| Sin releases hoy | 0 | 1 (select vacío) |
| 5 releases, todos salen | 5 | 6 (1 select + 5 updates) |
| 30 releases (peor caso) | 30 espaciados en ~90s | 31 |
| Fallback 03:00 | 0 | N updates |

---

## Comandos útiles

### Ver crontab actual

```bash
crontab -l
```

### Editar crontab

```bash
crontab -e
```

### Probar manualmente

```bash
cd /home/stephencurrygt30/musicappBETA

# Modo normal
/home/stephencurrygt30/musicappBETA/venv/bin/python scripts/check_releases.py

# Modo fallback
/home/stephencurrygt30/musicappBETA/venv/bin/python scripts/check_releases.py --fallback
```

### Ver log

```bash
cat /var/log/check_releases.log
```

### Ver últimas líneas del log en tiempo real

```bash
tail -f /var/log/check_releases.log
```

### Limpiar log

```bash
> /var/log/check_releases.log
```

### Verificar que cron está corriendo

```bash
systemctl status cron
```

---

## Agregar un nuevo cron

1. Crear el script en `scripts/`
2. Probarlo manualmente: `/home/stephencurrygt30/musicappBETA/venv/bin/python scripts/nuevo_script.py`
3. Agregar línea al crontab: `crontab -e`
4. Redirigir output a un log: `>> /var/log/nombre.log 2>&1`
5. Documentar acá

---

## Timezone

El cron corre en la timezone del servidor. Verificar con:

```bash
timedatectl
```

Si necesitás cambiarla:

```bash
sudo timedatectl set-timezone America/Argentina/Buenos_Aires
```

---

## Troubleshooting

| Problema | Solución |
|---|---|
| El cron no corre | `systemctl status cron` — verificar que el servicio esté activo |
| No hay output en el log | Verificar permisos: `ls -la /var/log/check_releases.log` |
| ModuleNotFoundError | Usar el python del venv, no el del sistema |
| El script falla silenciosamente | Correrlo manualmente y ver el error en consola |
| Timezone incorrecta | `timedatectl set-timezone America/Argentina/Buenos_Aires` |

---

## Referencias

> SEE: [Ubuntu — Crontab](https://manpages.ubuntu.com/manpages/noble/man5/crontab.5.html)
> SEE: [Crontab Guru — Editor visual](https://crontab.guru/)
> SEE: [GCP — Compute Engine](https://cloud.google.com/compute/docs)
> SEE: [Systemd — Cron service](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)
> DOC: [Upcoming Releases System](../upcoming_releases.md)