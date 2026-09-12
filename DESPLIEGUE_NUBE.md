# ☁️ Guía de Despliegue 24/7 en la Nube (Sin Servidor Propio ni PC Encendida)

Esta guía te permite dejar a **Griffin / LibroSync** funcionando de forma continua las 24 horas del día, los 365 días del año, sin que tengas que tener tu computadora encendida y sin tener que pagar ni administrar un servidor Linux.

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
4. Ve a la pestaña **Settings** de tu Space, baja hasta **Variables and secrets** y añade dos secretos (*New secret*):
   - `TELEGRAM_BOT_TOKEN` = Tu token de Telegram BotFather.
   - `GEMINI_API_KEY` = Tu clave API de Google Gemini.
5. Sube los archivos a tu Space:
   - Puedes clonar el repositorio de Hugging Face y copiar tu carpeta:
     ```bash
     git clone https://huggingface.co/spaces/TU_USUARIO/librosync-bot hf-space
     cp -r backend Dockerfile librosync.db hf-space/
     cd hf-space
     git add .
     git commit -m "Deploy Griffin Bot 24/7"
     git push
     ```
   - O bien, puedes arrastrar los archivos directamente en la pestaña **Files** de la web de Hugging Face.
6. ¡Listo! En 2 minutos verás en los logs: `✅ Bot de Telegram en línea y escuchando actualizaciones`. Ya puedes apagar tu PC y el bot seguirá respondiendo siempre.

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
   - `DATABASE_URL` = `sqlite+aiosqlite:///librosync.db`
6. Haz clic en **Deploy**. Cada vez que hagas `git push` a tu repositorio, el bot se actualizará solo.

---

## 🐳 Opción 3: Docker en tu PC o Mini-PC (Prueba Local Inmediata)

Si quieres probar el contenedor en tu máquina antes de subirlo:

```bash
# Construir e iniciar el contenedor en segundo plano con auto-reinicio
docker compose up -d

# Ver logs en vivo
docker compose logs -f

# Detener el contenedor
docker compose down
```
