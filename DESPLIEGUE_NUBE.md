# ☁️ Guía de Despliegue 24/7 en la Nube (Sin Servidor Propio ni PC Encendida)

Esta guía te permite dejar a **Griffin / LibroSync** funcionando de forma continua las 24 horas del día, los 365 días del año, sin que tengas que tener tu computadora encendida y sin tener que pagar ni administrar un servidor Linux.

> ⚠️ **Nunca subas `backend/.env` ni `librosync.db` a Git, Hugging Face ni ningún repositorio público.** La base contiene datos de usuarios y el `.env` contiene tokens. Usa siempre la sección **Variables and secrets** de la plataforma.

---

## 🌟 Opción 1: Hugging Face Spaces (Recomendada — 100% Gratis de por vida)

Hugging Face te da un contenedor Docker con **2 vCPU y 16 GB de RAM gratuitos** que nunca duerme.

### Pasos:
1. Crea una cuenta gratuita en [Hugging Face](https://huggingface.co/join) (si no tienes una).
2. Ve a [huggingface.co/new-space](https://huggingface.co/new-space) para crear un nuevo Space:
   - **Space name:** `librosync-bot`
   - **License:** `mit` (o cualquiera)
   - **Space SDK:** Selecciona **Docker** -> **Blank**
   - **Space hardware:** Deja el gratuito predeterminado (2 vCPU · 16 GB).
   - **Privacy:** `Private` (para que solo tú tengas acceso a tus datos).
3. Haz clic en **Create Space**.
4. Ve a la pestaña **Settings** de tu Space, baja hasta **Variables and secrets** y añade los secretos (*New secret*):
   - `TELEGRAM_BOT_TOKEN` = Tu token de Telegram BotFather.
   - `GEMINI_API_KEY` = Tu clave API de Google Gemini.
   - `ADMIN_TELEGRAM_IDS` = Tu ID numérico de Telegram (opcional, para mantenimiento global).
   - `ENVIRONMENT` = `production`.
   - `DEBUG` = `false`.
5. Sube **solo el código**, nunca tu `.env` ni la base de datos:
   ```bash
   git clone https://huggingface.co/spaces/TU_USUARIO/librosync-bot hf-space
   rsync -a --exclude 'backend/.env' --exclude 'backend/venv' \
     --exclude 'backend/tests' --exclude '*.db' --exclude '*.db-*' \
     --exclude 'storage' --exclude '__pycache__' \
     backend Dockerfile README.md hf-space/
   cd hf-space
   git add .
   git commit -m "Deploy Griffin Bot 24/7"
   git push
   ```
   También puedes arrastrar los archivos directamente en la pestaña **Files**, excluyendo `.env`, `venv`, tests y bases de datos.
6. ¡Listo! En 2 minutos verás en los logs: `✅ Bot de Telegram en línea y escuchando actualizaciones`. Ya puedes apagar tu PC y el bot seguirá respondiendo siempre.

> ℹ️ En Hugging Face el almacenamiento del contenedor puede ser efímero si el Space se reconstruye. Para conservar la biblioteca, descarga periódicamente `librosync.db` desde el Space o monta almacenamiento persistente si tu plan lo permite.

---

## 🚀 Opción 2: Koyeb (Despliegue Automático con GitHub)

Koyeb tiene una capa gratuita perpetua (*Free Tier*) sin tarjetas obligatorias:

1. Crea cuenta en [Koyeb.com](https://www.koyeb.com/).
2. Haz clic en **Create App** -> **GitHub**.
3. Selecciona tu repositorio de GitHub `Libreria`.
4. En **Builder**, selecciona **Dockerfile**.
5. En **Environment Variables**, añade:
   - `TELEGRAM_BOT_TOKEN` = Tu token
   - `GEMINI_API_KEY` = Tu clave de Gemini
   - `ENVIRONMENT` = `production`
   - `DEBUG` = `false`
   - `ADMIN_TELEGRAM_IDS` = Tu ID de Telegram
6. Añade un **Persistent Volume** montado en `/app/data`. Sin volumen persistente, la base SQLite se pierde en cada redeploy.
7. Haz clic en **Deploy**. Cada vez que hagas `git push` a tu repositorio, el bot se actualizará solo.

> El `Dockerfile` ya define `DATABASE_URL=sqlite+aiosqlite:////app/data/librosync.db`. No necesitas sobrescribirla si usas el volumen en `/app/data`.

---

## 🐳 Opción 3: Docker en tu PC o Mini-PC (Prueba Local Inmediata)

Si quieres probar el contenedor en tu máquina antes de subirlo:

```bash
# 1. Crea el archivo de entorno y protégelo
cp backend/.env.example backend/.env
chmod 600 backend/.env
# Edita backend/.env y define TELEGRAM_BOT_TOKEN y GEMINI_API_KEY

# 2. Construir e iniciar el contenedor en segundo plano con auto-reinicio
docker compose up -d --build

# 3. Ver logs en vivo
docker compose logs -f

# 4. Comprobar el health check
curl -fsS http://127.0.0.1:8000/

# 5. Detener el contenedor
docker compose down
```

El contenedor se ejecuta como usuario **no-root**, no incluye `.env` ni la base de datos en la imagen y persiste los datos en el volumen `librosync_data`.

### Copia de seguridad en Docker

```bash
docker compose stop
docker run --rm -v librosync_data:/data -v "$PWD":/backup alpine \
  sh -c 'cp /data/librosync.db /backup/librosync-backup.db'
chmod 600 librosync-backup.db
docker compose start
```

---

## 🔄 Actualizaciones y Migraciones

- Al arrancar, la aplicación crea/actualiza el esquema y aplica migraciones versionadas automáticamente.
- Las migraciones quedan registradas en la tabla `schema_migrations`.
- Antes de actualizar en producción, haz una copia de seguridad de la base.
- Si cambias de versión y algo falla, revisa los logs del contenedor:

```bash
docker compose logs --tail=200
```

---

## 🔐 Checklist de Seguridad en Producción

- [ ] `backend/.env` tiene permisos `600` y nunca se commitea.
- [ ] `librosync.db` no está en Git ni en la imagen Docker.
- [ ] `DEBUG=false` y `ENVIRONMENT=production`.
- [ ] `SECRET_KEY` es aleatoria y distinta en cada despliegue.
- [ ] `ADMIN_TELEGRAM_IDS` contiene solo tus IDs de confianza.
- [ ] El token de Telegram y la API key de Gemini están en *secrets* de la plataforma, no en texto plano.
- [ ] Se hace copia de seguridad periódica de la base y se almacena cifrada.
- [ ] Si un token se expone, se revoca inmediatamente en BotFather / Google AI Studio / GitHub.
