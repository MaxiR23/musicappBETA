# Deploy Process — Backend Beatly

## Resumen

Deploy manual desde PC local al servidor GCP via SSH. Un solo comando ejecuta `git pull` + `systemctl restart`.

```
┌──────────────┐      SSH       ┌──────────────────┐
│   PC Local   │ ──────────────▶│  beatly-api (GCP) │
│  git push    │                │  ~/deploy.sh      │
│  ssh deploy  │                │  git pull + restart│
└──────────────┘                └──────────────────┘
```

---

## Requisitos

| Componente | Valor |
|---|---|
| Servidor | `beatly-api` (GCP Compute Engine) |
| IP | `<SERVER_IP>` |
| Usuario SSH | `<SSH_USER>` |
| Key local | `~/.ssh/id_ed25519` |
| Service | `beatly` (systemd) |
| Repo en server | `~/musicappBETA` |

> Los valores reales de `<SERVER_IP>` y `<SSH_USER>` están en el archivo `.env` local o en los secrets del equipo.

---

## Deploy (día a día)

### Desde PC local

```bash
# 1. Push cambios a main
git push origin main

# 2. Conectar al servidor
ssh <SSH_USER>@<SERVER_IP>

# 3. Ejecutar deploy
./deploy.sh
```

### Output esperado

```
[deploy] Pulling latest code...
From github.com:user/repo
 * branch            main       -> FETCH_HEAD
Already up to date.
[deploy] Restarting beatly...
[deploy] Done! Wed Apr  8 01:50:37 UTC 2026
```

---

## Deploy Script

**Ubicación en servidor:** `~/deploy.sh`

```bash
#!/bin/bash
set -e

cd ~/musicappBETA

echo "[deploy] Pulling latest code..."
git pull origin main

echo "[deploy] Restarting beatly..."
sudo systemctl restart beatly

echo "[deploy] Done! $(date)"
```

> `set -e` hace que el script se detenga si cualquier comando falla.
> `systemctl restart` para y levanta el servicio limpio.

---

## Setup SSH (una sola vez)

### 1. Generar key pair en PC local

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
```

Genera `id_ed25519` (privada) y `id_ed25519.pub` (pública).

### 2. Agregar key pública al servidor

Desde la consola web de GCP (Compute Engine → SSH), ejecutar:

```bash
echo "CONTENIDO_DE_id_ed25519.pub" >> ~/.ssh/authorized_keys
```

### 3. Verificar conexión desde PC local

```bash
ssh <SSH_USER>@<SERVER_IP>
```

---

## Sudoers (una sola vez)

Para que `systemctl restart beatly` no pida password:

```bash
sudo visudo -f /etc/sudoers.d/beatly-deploy
```

Contenido:

```
<SSH_USER> ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart beatly
```

> Solo permite restart de `beatly`, nada más. Cualquier otro comando sigue pidiendo password.

---

## Verificación post-deploy

```bash
# Ver estado del servicio
sudo systemctl status beatly

# Ver últimos logs
journalctl -u beatly -n 50 --no-pager

# Verificar que responde
curl http://localhost:<PORT>/api/health
```

---

## Troubleshooting

| Problema | Solución |
|---|---|
| `Permission denied (publickey)` | Verificar que la key pública esté en `~/.ssh/authorized_keys` del servidor |
| `deploy.sh: Permission denied` | `chmod +x ~/deploy.sh` en el servidor |
| `sudo: a password is required` | Verificar `/etc/sudoers.d/beatly-deploy` con `sudo visudo -f /etc/sudoers.d/beatly-deploy` |
| `git pull` falla | Verificar acceso al repo con `git remote -v` en el servidor |
| Servicio no arranca | `journalctl -u beatly -n 100 --no-pager` para ver logs de error |

---

## Notas

- **No hace falta parar fail2ban** para deployar. Es un servicio independiente que monitorea logs.
- **El deploy script vive en el servidor**, no en el repo. Este doc es solo referencia.
- **Futuro:** si se quiere automatizar con GitHub Actions (push a main = deploy automático), se necesita agregar la key privada como Secret en GitHub y crear un workflow. Ver referencias abajo.

---

## Referencias

> SEE: [SSH Key Generation (GitHub Docs)](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent)
> SEE: [sudoers Manual](https://man7.org/linux/man-pages/man5/sudoers.5.html)
> SEE: [systemd Service Management](https://www.freedesktop.org/software/systemd/man/latest/systemctl.html)
> SEE: [GitHub Actions — appleboy/ssh-action (para futuro CI/CD)](https://github.com/appleboy/ssh-action)
> SEE: [Google — SSH to Compute Engine](https://cloud.google.com/compute/docs/connect/standard-ssh)