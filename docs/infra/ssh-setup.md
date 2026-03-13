# SSH desde PC — Configuración GCP

## Qué hicimos

Configuramos acceso SSH desde Windows a la VM de GCP (Beatly API) usando un **par de claves ed25519**, sin contraseña, sin consola web.

---

## Por qué claves y no contraseñas

- Las contraseñas son vulnerables a fuerza bruta
- Las claves ed25519 son criptográficamente fuertes — para robar acceso alguien necesitaría el archivo físico de tu PC
- Es el estándar en cualquier equipo de infra profesional

---

## Archivos generados

| Archivo | Descripción |
|---|---|
| `C:\Users\{usuario}\.ssh\id_ed25519` | Clave **privada** — nunca compartir, nunca subir a ningún lado |
| `C:\Users\{usuario}\.ssh\id_ed25519.pub` | Clave **pública** — la que se sube al servidor |

---

## Cómo se configuró

### 1. Generar el par de claves (en PowerShell)

```powershell
ssh-keygen -t ed25519 -C "nombre-descriptivo"
```

- Ruta: dejar la que sugiere por defecto → Enter
- Passphrase: vacío → Enter

### 2. Copiar la clave pública al servidor

Desde la consola web de GCP (una sola vez):

```bash
mkdir -p ~/.ssh && echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHj7mK2pQnVxLsT9eRuWdYoF3bZcXgNiAqPvOkMwE ejemplo-inventado"
# ^ clave de ejemplo inventada — reemplazar con el contenido real de tu id_ed25519.pub >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && chmod 700 ~/.ssh
```

> El contenido de `id_ed25519.pub` se obtiene con:
> ```powershell
> Get-Content C:\Users\{usuario}\.ssh\id_ed25519.pub
> ```

### 3. Conectarse

```powershell
ssh -i ~/.ssh/id_ed25519 usuario@IP_DE_LA_VM
```

---

## Importante

- Si la VM se **reinicia**, el archivo `~/.ssh/authorized_keys` puede borrarse (comportamiento de GCP con OS Login activo). Hay que repetir el paso 2.
- Este problema se resuelve de forma permanente en el ítem **#6 — IP estática + desactivar OS Login** (pendiente).
- `~/.ssh/` en Windows a veces no resuelve correctamente. Si falla, usar la ruta completa: `C:\Users\{usuario}\.ssh\id_ed25519`

---

## Referencias para estudiar

| Tema | Link |
|---|---|
| Cómo funciona SSH (conceptos) | https://www.ssh.com/academy/ssh |
| Ed25519 vs RSA — por qué ed25519 | https://blog.petehouston.com/ed25519-vs-rsa-for-ssh/ |
| ssh-keygen — documentación oficial | https://man.openbsd.org/ssh-keygen |
| Authorized keys — cómo funciona | https://www.ssh.com/academy/ssh/authorized-keys |
| GCP — OS Login vs metadata SSH keys | https://cloud.google.com/compute/docs/oslogin |

---

## Estado

| Item | Estado |
|---|---|
| Par de claves ed25519 generado | OK |
| Clave pública en el servidor | OK |
| Conexión desde PowerShell validada | OK |