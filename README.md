# 🔄 Sincronización PCO People → Loyverse POS

Sincroniza automáticamente personas de **Planning Center Online** como
clientes en **Loyverse POS**, filtrando solo mayores de 18 años y
guardando el RUT en código de cliente y notas.

---

## 📁 Estructura del proyecto

```
pco-loyverse-sync/
├── sync.py              ← El script principal
├── Dockerfile           ← Empaqueta todo en un contenedor
├── docker-compose.yml   ← Facilita la ejecución local
├── railway.json         ← Configuración para Railway (nube)
├── requirements.txt     ← Dependencias Python
├── .env.example         ← Plantilla de configuración
├── .gitignore           ← Protege tus credenciales
└── README.md            ← Este archivo
```

---

## 🖥️ PARTE 1: Ejecutar localmente en Windows 11

### Paso 1 — Instalar Docker Desktop

1. Ve a **https://www.docker.com/products/docker-desktop/**
2. Descarga e instala **Docker Desktop for Windows**
3. Al instalar, acepta activar **WSL 2** si lo pide (es el backend recomendado)
4. Reinicia el PC cuando te lo pida
5. Abre Docker Desktop y espera a que diga **"Engine running"**

> **Verificar que funciona:** Abre PowerShell y escribe:
> ```
> docker --version
> ```
> Debe mostrar algo como `Docker version 27.x.x`

---

### Paso 2 — Instalar Git (para descargar el proyecto)

1. Ve a **https://git-scm.com/download/win**
2. Descarga el instalador y ejecútalo con las opciones por defecto
3. Verifica: `git --version` en PowerShell

---

### Paso 3 — Descargar este proyecto

Abre **PowerShell** y ejecuta:

```powershell
# Ir al escritorio (o donde prefieras)
cd $HOME\Desktop

# Clonar el repositorio (reemplaza con tu URL de GitHub cuando lo subas)
git clone https://github.com/TU_USUARIO/pco-loyverse-sync.git

# Entrar a la carpeta
cd pco-loyverse-sync
```

---

### Paso 4 — Configurar tus credenciales

1. En la carpeta del proyecto, copia el archivo de ejemplo:

```powershell
copy .env.example .env
```

2. Abre el archivo `.env` con el Bloc de Notas:

```powershell
notepad .env
```

3. Rellena los valores:

```env
PCO_APP_ID=tu_application_id_de_pco
PCO_SECRET=tu_secret_de_pco
LOYVERSE_TOKEN=tu_token_de_loyverse
PCO_RUT_FIELD_NAME=RUT
DRY_RUN=true     ← Empieza en true para probar sin riesgo
```

#### ¿Dónde obtengo las credenciales?

**Planning Center Online:**
1. Ve a https://api.planningcenteronline.com/oauth/applications
2. Haz clic en **"New Application"**
3. Dale un nombre (ej: "Integración Loyverse")
4. En la sección **"Personal Access Tokens"**, crea un token
5. Copia el **Application ID** y el **Secret**

**Loyverse:**
1. Abre el **Back Office** en https://r.loyverse.com/dashboard
2. Ve a **Configuración → Acceso API**
3. Haz clic en **"+ Agregar token de acceso"**
4. Nómbralo (ej: "Integración PCO") y guarda
5. Copia el token que aparece

---

### Paso 5 — Construir y ejecutar

```powershell
# Construir la imagen (solo la primera vez, tarda 1-2 minutos)
docker compose build

# Ejecutar la sincronización
docker compose up
```

Verás los logs en pantalla. Al terminar, los logs también quedarán
guardados en `.\logs\sync_log.txt`.

---

### Paso 6 — Verificar el resultado

Con `DRY_RUN=true`, el log mostrará qué haría el script sin modificar
nada en Loyverse:

```
[DRY RUN] CREAR: {'name': 'Juan Pérez', 'email': 'juan@...' ...}
```

Cuando estés conforme, cambia en `.env`:
```
DRY_RUN=false
```

Y vuelve a ejecutar:
```powershell
docker compose up
```

---

### Ejecución manual futura

Cada vez que quieras sincronizar manualmente:

```powershell
cd $HOME\Desktop\pco-loyverse-sync
docker compose up
```

---

## ☁️ PARTE 2: Ejecución automática en Railway (nube)

Railway ejecutará el script automáticamente según el horario que
configures (ej: todos los días a las 3 AM). Es **gratuito** para
este tipo de uso.

### Paso 1 — Subir el proyecto a GitHub

```powershell
# Inicializar Git en la carpeta (si no lo hiciste ya)
cd $HOME\Desktop\pco-loyverse-sync
git init
git add .
git commit -m "Integración PCO → Loyverse"

# Crear repositorio en GitHub:
# 1. Ve a https://github.com/new
# 2. Ponle un nombre (ej: pco-loyverse-sync)
# 3. Déjalo PRIVADO (tus credenciales NO están en el repo, pero por seguridad)
# 4. Copia la URL del repositorio

git remote add origin https://github.com/TU_USUARIO/pco-loyverse-sync.git
git branch -M main
git push -u origin main
```

> ✅ El archivo `.gitignore` ya excluye `.env`, así que tus
> credenciales NO se subirán a GitHub.

---

### Paso 2 — Crear cuenta en Railway

1. Ve a **https://railway.com**
2. Haz clic en **"Start a New Project"**
3. Conéctate con tu cuenta de **GitHub**

---

### Paso 3 — Crear el proyecto en Railway

1. En el dashboard de Railway, haz clic en **"New Project"**
2. Selecciona **"Deploy from GitHub repo"**
3. Elige tu repositorio `pco-loyverse-sync`
4. Railway detectará el `Dockerfile` automáticamente

---

### Paso 4 — Agregar las variables de entorno en Railway

1. En tu proyecto de Railway, haz clic en el servicio creado
2. Ve a la pestaña **"Variables"**
3. Agrega cada variable haciendo clic en **"New Variable"**:

| Variable | Valor |
|---|---|
| `PCO_APP_ID` | tu application id de PCO |
| `PCO_SECRET` | tu secret de PCO |
| `LOYVERSE_TOKEN` | tu token de Loyverse |
| `PCO_RUT_FIELD_NAME` | `RUT` |
| `DRY_RUN` | `false` |

---

### Paso 5 — Configurar el horario (Cron)

El archivo `railway.json` ya incluye la configuración para ejecutarse
**todos los días a las 3 AM (UTC)**. Si quieres otro horario:

1. En Railway → tu servicio → pestaña **"Settings"**
2. Busca la sección **"Cron Schedule"**
3. Modifica el valor usando formato cron:

```
# Formato: minuto hora día mes día_semana
0 3 * * *     → todos los días a las 3:00 AM UTC (= 00:00 Chile)
0 6 * * *     → todos los días a las 6:00 AM UTC (= 03:00 Chile)
0 6 * * 1     → todos los lunes a las 6:00 AM UTC
0 6 1 * *     → el 1er día de cada mes
```

> **Nota horaria:** Chile está en UTC-3 (UTC-4 en verano).
> Para que corra a medianoche hora Chile: usa `0 3 * * *` en verano
> o `0 4 * * *` en invierno.

---

### Paso 6 — Verificar primera ejecución

1. En Railway, haz clic en **"Deploy"** para forzar una primera ejecución
2. Ve a la pestaña **"Deployments"** para ver los logs en tiempo real
3. Verifica que el resumen final muestre los clientes creados/actualizados

---

## 🔒 Seguridad

- Las credenciales **nunca** se guardan en el código ni en Git
- Se usan exclusivamente mediante variables de entorno
- El repositorio de GitHub debe ser **privado**
- Railway encripta las variables de entorno en reposo

---

## 🛠️ Solución de problemas

| Error | Causa probable | Solución |
|---|---|---|
| `KeyError: 'PCO_APP_ID'` | Falta el archivo `.env` | Crea `.env` desde `.env.example` |
| `401 Unauthorized` en PCO | Credenciales incorrectas | Verifica APP_ID y SECRET en PCO |
| `401 Unauthorized` en Loyverse | Token inválido | Regenera el token en Loyverse |
| `No hay adultos para sincronizar` | Personas sin `birthdate` en PCO | Completar fecha de nacimiento en PCO |
| Docker no inicia | WSL 2 no habilitado | Reinstala Docker Desktop activando WSL 2 |

---

## 📊 Logs

Los logs se guardan en `./logs/sync_log.txt` (local) o en el panel
de Railway (nube). Un resumen de cada ejecución luce así:

```
──────────────────────────────────────────────────
  RESUMEN FINAL
  Creados:      45
  Actualizados: 12
  Simulados:    0
  Errores:      0
──────────────────────────────────────────────────
  Sincronización completada.
```
