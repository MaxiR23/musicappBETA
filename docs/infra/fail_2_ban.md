# Fail2ban — Beatly API

## Qué hicimos

Instalamos y configuramos **fail2ban** en la VM de GCP para bloquear automáticamente IPs que intentan entrar al servidor por fuerza bruta vía SSH.

---

## Cómo funciona

Fail2ban monitorea archivos de log del sistema. Cuando detecta demasiados intentos fallidos desde una misma IP, la bloquea a nivel de firewall (iptables) por un tiempo determinado.

```
IP atacante → intenta SSH → falla → falla → falla → falla → falla
                                                              ↓
                                              fail2ban detecta 5 fallos en 10 min
                                                              ↓
                                              IP bloqueada por 1 hora
```

---

## Instalación

```bash
sudo apt install fail2ban -y
sudo systemctl status fail2ban
```

---

## Configuración aplicada

Archivo: `/etc/fail2ban/jail.local`

```ini
[sshd]
enabled  = true
maxretry = 5
bantime  = 3600
findtime = 600
```

| Parámetro | Valor | Descripción |
|---|---|---|
| `enabled` | true | Activa la jail de SSH |
| `maxretry` | 5 | Intentos fallidos antes de banear |
| `findtime` | 600 | Ventana de tiempo en segundos (10 min) |
| `bantime` | 3600 | Duración del bloqueo en segundos (1 hora) |

> `jail.local` siempre tiene prioridad sobre `jail.conf`. Nunca editar `jail.conf` directamente — se pisa con actualizaciones del sistema.

---

## Comandos útiles

```bash
# Ver estado general
sudo fail2ban-client status

# Ver estado de la jail de SSH (IPs baneadas, intentos, etc.)
sudo fail2ban-client status sshd

# Desbanear una IP manualmente
sudo fail2ban-client set sshd unbanip 1.2.3.4

# Reiniciar después de cambiar configuración
sudo systemctl restart fail2ban

# Ver logs de fail2ban
sudo tail -f /var/log/fail2ban.log
```

---

## Archivos importantes

| Archivo | Descripción |
|---|---|
| `/etc/fail2ban/jail.conf` | Config por defecto — no editar |
| `/etc/fail2ban/jail.local` | Config local — nuestros cambios van acá |
| `/var/log/auth.log` | Log de autenticación SSH que fail2ban monitorea |
| `/var/log/fail2ban.log` | Log propio de fail2ban |

---

## Estado

| Item | Estado |
|---|---|
| fail2ban instalado | OK |
| Jail SSH activa | OK |
| 5 intentos → 1 hora de bloqueo | OK |
| Servicio habilitado al inicio | OK |

---

## Referencias para estudiar

| Tema | Link |
|---|---|
| Fail2ban — documentación oficial | https://www.fail2ban.org/wiki/index.php/MANUAL_0_8 |
| Fail2ban — guía en Debian | https://wiki.debian.org/fail2ban |
| Cómo funciona iptables | https://www.netfilter.org/documentation |
| Ataques de fuerza bruta SSH | https://www.ssh.com/academy/ssh/security |
| jail.local vs jail.conf | https://github.com/fail2ban/fail2ban/wiki/Proper-fail2ban-configuration |