# Google Cloud Platform — VM Setup para Backend FastAPI

## Qué hicimos

Desplegamos el backend de Beatly en una **VM de Google Cloud Platform** (Compute Engine) para aprovechar la baja latencia a los servidores de YouTube desde la red de Google.

**Infraestructura:**

| Componente | Valor |
|---|---|
| Proveedor | Google Cloud Platform |
| Servicio | Compute Engine (VM) |
| Región | `southamerica-east1` (São Paulo) |
| Tipo de máquina | `e2-medium` (2 vCPU, 4GB RAM) |
| OS | Debian GNU/Linux 12 (bookworm) |
| Puerto | 8080 |
| IP Externa | `34.39.241.17` |

---

## Por qué VM y no Cloud Run

Evaluamos dos opciones:

| Criterio | Cloud Run | VM (Compute Engine) |
|---|---|---|
| Setup | Requiere Docker | Directo (git clone, pip install) |
| Dependencias | Conflictos con `--no-deps` | Resolver nativo de pip funciona |
| Costo testing | ~$0 (pay per request) | ~$26/mes (24/7) |
| Control | Limitado | Total |
| Mantenimiento | Google | Manual |

**Elegimos VM** porque Cloud Run requería Docker y tuvimos conflictos de dependencias irresolubles entre `httpx`, `gotrue` e `innertube`.

---

## Estructura del deploy

```
┌─────────────────────────────────────────────────────┐
│                  Google Cloud Platform              │
│  ┌───────────────────────────────────────────────┐  │
│  │            southamerica-east1 (São Paulo)     │  │
│  │  ┌─────────────────────────────────────────┐  │  │
│  │  │           VM: beatly-api                │  │  │
│  │  │  ┌───────────────────────────────────┐  │  │  │
│  │  │  │  Python 3.11 + venv               │  │  │  │
│  │  │  │  uvicorn → FastAPI app            │  │  │  │
│  │  │  │  Puerto: 8080                     │  │  │  │
│  │  │  └───────────────────────────────────┘  │  │  │
│  │  └─────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────┘  │
│                         │                           │
│              Firewall: allow-8080                   │
│                         │                           │
└─────────────────────────┼───────────────────────────┘
                          │
                          ▼
                   Internet (0.0.0.0/0)
                          │
                          ▼
              ┌───────────────────────┐
              │   Beatly App (Expo)   │
              │   EXPO_PUBLIC_API_URL │
              └───────────────────────┘
```

---

## Setup paso a paso

### 1. Crear cuenta en GCP

```
https://console.cloud.google.com
```

- Free Trial: $300 de crédito por 90 días
- Requiere tarjeta (verificación, no cobra)

### 2. Crear la VM

**Compute Engine → VM instances → Create instance**

```yaml
Name: beatly-api
Region: us-central1 (Iowa)
Zone: us-central1-a
Machine type: e2-standard-2
OS: Debian GNU/Linux 12

Networking:
  - Allow HTTP traffic: [x]
  - Allow HTTPS traffic: [x]
  - Firewall rule allow-39477: [x]

Pending:
  - Static IP: [ ]
  - Disable OS Login: [ ]
```

### 3. Configurar Firewall

**VPC network → Firewall → Create Firewall Rule**

```yaml
Name: allow-8080
Direction: Ingress
Targets: All instances in the network
Source IP ranges: 0.0.0.0/0
Protocols and ports:
  - TCP: 8080
```

### 4. Conectar via SSH

**Compute Engine → VM instances → SSH** (columna Connect)

### 5. Instalar dependencias

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv git
```

### 6. Clonar repositorio

```bash
git clone https://github.com/MaxiR23/musicappBETA.git
```

> Para repos privados, usar Personal Access Token:
> `https://github.com/settings/tokens` → Generate new token (classic) → scope `repo`

### 7. Setup del entorno

```bash
cd musicappBETA
python3 -m venv venv
source venv/bin/activate
pip install --use-deprecated=legacy-resolver -r requirements.txt
```

> Se usa `--use-deprecated=legacy-resolver` para evitar conflictos entre `httpx`, `gotrue` etc

### 8. Configurar variables de entorno

```bash
nano .env
```

Pegar contenido del `.env` local → `Ctrl+X`, `Y`, `Enter`

### 9. Ejecutar servidor

```bash
# Modo desarrollo (se detiene al cerrar SSH)
python3 -m uvicorn app:app --host 0.0.0.0 --port 8080

# Modo background (persiste al cerrar SSH)
nohup python3 -m uvicorn app:app --host 0.0.0.0 --port 8080 &
```

---

## Comandos de operación

### Iniciar servidor

```bash
cd musicappBETA && source venv/bin/activate && python3 -m uvicorn app:app --host 0.0.0.0 --port 8080
```

### Actualizar código

```bash
cd musicappBETA && git pull && source venv/bin/activate && python3 -m uvicorn app:app --host 0.0.0.0 --port 8080
```

### Ver procesos en puerto 8080

```bash
lsof -i :8080
```

### Matar proceso en puerto 8080

```bash
kill $(lsof -t -i:8080)
```

### Ver logs de nohup

```bash
cat nohup.out
```

### Limpiar logs de nohup

```bash
> nohup.out
```

---

## Control de la VM

### Pausar (no cobra mientras está pausada)

**Compute Engine → VM instances → ⋮ → Stop**

### Reanudar

**Compute Engine → VM instances → ⋮ → Start**

> La IP externa puede cambiar al reiniciar. Para IP fija, reservar IP estática.

---

## Configuración del frontend

**`app.json`** (Expo):

```json
{
  "extra": {
    "EXPO_PUBLIC_API_URL": "http://34.39.241.17:8080/api"
  }
}
```

---

## Costos

| Recurso | Costo mensual |
|---|---|
| e2-medium (24/7) | ~$25 |
| Disco 10GB | ~$1 |
| Egress (tráfico saliente) | Variable |
| **Total estimado** | **~$26/mes** |

Con $300 de crédito → ~11 meses de uso continuo.

---

## Troubleshooting

| Problema | Solución |
|---|---|
| `Address already in use` | `kill $(lsof -t -i:8080)` |
| `Permission denied` al clonar | Verificar scope `repo` en token |
| `Module not found` | `source venv/bin/activate` |
| App no conecta | Verificar VM corriendo + firewall + IP correcta |

---

## Próximos pasos

- [ ] SSH desde PC local (no usar consola web)
- [ ] Rama `production` limpia separada de `main`
- [ ] systemd service para auto-restart
- [ ] IP estática reservada
- [ ] HTTPS con certificado SSL (Let's Encrypt)
- [ ] Dominio personalizado
- [ ] CI/CD: auto-deploy en push a `production`

---

## Referencias

> SEE: [GCP — Compute Engine Quickstart](https://cloud.google.com/compute/docs/quickstart-linux)  
> SEE: [GCP — Firewall Rules](https://cloud.google.com/vpc/docs/firewalls)  
> SEE: [GCP — Static External IP](https://cloud.google.com/compute/docs/ip-addresses/reserve-static-external-ip-address)  
> SEE: [GCP — Free Tier](https://cloud.google.com/free)  
> SEE: [GitHub — Personal Access Tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)  
> SEE: [Uvicorn — Deployment](https://www.uvicorn.org/deployment/)  
> SEE: [FastAPI — Deployment](https://fastapi.tiangolo.com/deployment/)
