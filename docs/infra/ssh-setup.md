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

### 1. Generar el par de claves (en PowerShell o terminal de VSCode)
```powershell
ssh-keygen -t ed25519 -C "nombre-descriptivo"
```

- Ruta: dejar la que sugiere por defecto → Enter
- Passphrase: vacío → Enter

### 2. Obtener la clave pública
```powershell
Get-Content C:\Users\{usuario}\.ssh\id_ed25519.pub
```

Copiá el output completo — es una sola línea que empieza con `ssh-ed25519`.

### 3. Agregar la clave pública al servidor

Desde la consola web de GCP, conectarse a la VM y correr:
```bash
echo "PEGAR_CLAVE_PUBLICA_ACA" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && chmod 700 ~/.ssh
```

### 4. Configurar la clave del servidor en GitHub (para clonar repos privados)

Desde la VM, generar un par de claves separado para GitHub:
```bash
ssh-keygen -t ed25519 -C "nombre-descriptivo"
cat ~/.ssh/id_ed25519.pub
```

Ir a GitHub → Settings → SSH and GPG keys → New SSH key → título descriptivo → tipo **Authentication Key** → pegar la clave pública.

Verificar conexión:
```bash
ssh -T git@github.com
```

Output esperado: `Hi {usuario}! You've successfully authenticated`

### 5. Conectarse desde la PC
```powershell
ssh {usuario-servidor}@IP_DE_LA_VM
```

---

## Importante

- Si la VM se **reinicia**, el archivo `~/.ssh/authorized_keys` puede borrarse (comportamiento de GCP con OS Login activo). Hay que repetir el paso 3.
- Este problema se resuelve de forma permanente desactivando OS Login y fijando una IP estática (pendiente).
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
| Par de claves ed25519 generado en PC local | OK |
| Clave pública local agregada al servidor | OK |
| Clave ed25519 del servidor agregada a GitHub | OK |
| Conexión desde VSCode/PowerShell validada | OK |
| IP estática configurada | Pendiente |
| OS Login desactivado | Pendiente |