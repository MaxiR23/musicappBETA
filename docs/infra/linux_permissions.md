# Linux — Permisos y Usuarios (Cheatsheet)

## Conceptos clave

- En Linux cada archivo y proceso pertenece a un **usuario** y un **grupo**
- `sudo` permite ejecutar comandos como superusuario (root) temporalmente
- Solo los usuarios en el grupo `sudo` pueden usar `sudo`

---

## Grupos

```bash
# Ver a qué grupos pertenece un usuario
groups nombre_usuario

# Agregar un usuario a un grupo
sudo usermod -aG nombre_grupo nombre_usuario

# -a = append (no lo saca de otros grupos)
# -G = Groups (lista de grupos)
```

> Después de agregar a un grupo, el usuario debe cerrar sesión y volver a entrar para que tome efecto.

### Grupos comunes

| Grupo | Qué permite |
|---|---|
| `sudo` | Ejecutar comandos como root |
| `docker` | Usar Docker sin sudo |
| `adm` | Leer logs del sistema |
| `www-data` | Acceso a archivos web (nginx, apache) |

---

## Contraseñas

```bash
# Cambiar la contraseña de tu propio usuario
passwd

# Cambiar la contraseña de otro usuario (requiere sudo)
sudo passwd nombre_usuario
```

---

## sudo

```bash
# Ejecutar un comando como root
sudo comando

# Abrir una shell como root
sudo -i

# Ver qué puede hacer tu usuario con sudo
sudo -l
```

---

## Permisos de archivos

```bash
# Ver permisos de archivos
ls -la

# Cambiar permisos
chmod 600 archivo   # solo el dueño puede leer y escribir
chmod 700 carpeta   # solo el dueño puede leer, escribir y entrar
chmod 755 archivo   # dueño todo, otros solo leer/ejecutar

# Cambiar dueño
sudo chown usuario:grupo archivo
```

### Permisos SSH (obligatorios)

| Archivo | Permiso | Comando |
|---|---|---|
| `~/.ssh/` | 700 | `chmod 700 ~/.ssh` |
| `~/.ssh/authorized_keys` | 600 | `chmod 600 ~/.ssh/authorized_keys` |
| `~/.ssh/id_ed25519` (clave privada) | 600 | `chmod 600 ~/.ssh/id_ed25519` |

> Si los permisos de estos archivos son muy permisivos, SSH rechaza la conexión por seguridad.

---

## Usuarios

```bash
# Ver todos los usuarios del sistema
cat /etc/passwd

# Ver usuario actual
whoami

# Cambiar a otro usuario
su - nombre_usuario

# Crear un usuario nuevo
sudo adduser nombre_usuario

# Eliminar un usuario
sudo deluser nombre_usuario
```

---

## Lo que hicimos en Beatly

```bash
# stephencurrygt30 no tenía permisos sudo
# Lo agregamos al grupo sudo desde la consola web de GCP:
sudo usermod -aG sudo stephencurrygt30

# Seteamos contraseña para poder usar sudo
sudo passwd stephencurrygt30

# Verificamos los grupos del usuario
groups stephencurrygt30
```

---

## Referencias para estudiar

| Tema | Link |
|---|---|
| Permisos en Linux — guía completa | https://www.linux.org/threads/file-permissions.4214 |
| sudo — documentación | https://www.sudo.ws/docs/man/sudo.man |
| chmod — referencia | https://man7.org/linux/man-pages/man1/chmod.1.html |
| usermod — referencia | https://man7.org/linux/man-pages/man8/usermod.8.html |
| SSH y permisos de archivos | https://www.ssh.com/academy/ssh/authorized-keys-file |