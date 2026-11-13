---
title: LibroSync Bot
emoji: 📚
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 8000
pinned: false
---

# 📚 Griffin / LibroSync — Bot de Telegram para Biblioteca Digital Inteligente

Griffin es un bibliotecario digital autónomo para Telegram con soporte para ingesta cero fricción, análisis con IA (Google Gemini), organización en temas/topics, seguimiento de lectura y catálogos interactivos.

## 🚀 Características
- **Modo Cero Fricción:** Sube libros en formato PDF, EPUB, MOBI, CBR o CBZ directamente al chat.
- **Clasificación con IA:** Identificación automática de título, autor, género literario, año y sagas.
- **Aislamiento Multigrupo:** Gestión de múltiples grupos de lectura con bibliotecas independientes y códigos de vinculación con expiración configurable.
- **Biblioteca Personal:** Modo privado 1 a 1 para gestionar tu acervo personal.
- **Club de Lectura:** Lecturas conjuntas (`/leerjuntos`), estantes personales (`/mislibros`) y registro de avance (`/progreso`).
- **Búsqueda y Descarga:** Búsqueda en español e inglés en Internet Archive, Project Gutenberg y Library Genesis, conservando variantes EPUB/PDF e idioma.
- **Seguridad:** Descargas con TLS verificado, límites de tamaño y protección contra SSRF; comandos destructivos solo para administradores.

## ⚡ Inicio Rápido Local

Requisitos: Python 3.11+ y un token de [@BotFather](https://t.me/BotFather).

```bash
cd backend
python3 -m venv venv
venv/bin/pip install -r requirements.txt

cp .env.example .env
chmod 600 .env
# Edita .env y define TELEGRAM_BOT_TOKEN, GEMINI_API_KEY y ADMIN_TELEGRAM_IDS

cd ..
./run.sh
```

El bot inicia el polling de Telegram y un health check en `http://127.0.0.1:8000/`.

### Variables importantes

| Variable | Descripción |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token de BotFather. Obligatorio. |
| `GEMINI_API_KEY` | Clave de Google Gemini para clasificación y chat. |
| `ADMIN_TELEGRAM_IDS` | IDs de Telegram con permisos globales, separados por comas. |
| `DATABASE_URL` | Por defecto `sqlite+aiosqlite:///.../librosync.db`. |
| `ENVIRONMENT` | Usa `production` en despliegues reales. |
| `DEBUG` | Déjalo en `False`; evita volcar detalles internos y SQL. |
| `ENABLE_NETWORK_PATCH` | Workaround de DNS para ISPs que bloquean Telegram. Desactivado por defecto. |
| `SEARCH_RATE_LIMIT` / `DOWNLOAD_RATE_LIMIT` | Límite de peticiones por ventana de tiempo. |

## 🛡️ Seguridad y Privacidad

- **Nunca subas** `backend/.env`, `librosync.db`, `storage/` ni logs a Git. Están en `.gitignore`.
- En el servidor, `backend/.env` debe tener permisos `600` (`chmod 600 backend/.env`).
- La base SQLite contiene datos de usuarios y bibliotecas: trátala como información sensible y haz copias de seguridad cifradas.
- Si un token o API key se expone, revócalo de inmediato:
  - Telegram: BotFather → `/revoke`.
  - Gemini: Google AI Studio → API keys.
  - GitHub: Settings → Developer settings → Personal access tokens.
- Los comandos destructivos (`/sincronizar`, `/deduplicar`, `/reorganizar`, recuperación de libros) exigen ser administrador del grupo. En chats privados solo el dueño de la biblioteca puede ejecutarlos.
- Las vinculaciones de grupo (`/start <código>`) solo las puede realizar un administrador del grupo.
- No se permite desactivar la verificación TLS en las descargas. Las URLs internas, `localhost` y direcciones privadas se rechazan.

## 🗄️ Base de Datos y Migraciones

Al arrancar, la aplicación aplica migraciones versionadas de forma idempotente y registra la versión en `schema_migrations`. No necesitas ejecutar `ALTER TABLE` manualmente.

- SQLite usa `foreign_keys=ON`, `busy_timeout`, WAL y `synchronous=NORMAL`.
- Para respaldar la base local: detén el bot y copia `librosync.db` (o usa `sqlite3 librosync.db ".backup copia.db"`).
- Nunca reemplaces la base en caliente mientras el bot está escribiendo.

## 🐳 Docker

El contenedor:

- Se ejecuta como usuario no-root.
- No copia `.env` ni bases de datos dentro de la imagen.
- Guarda la base y los archivos en el volumen `librosync_data` montado en `/app/data`.
- Incluye health check y arranque automático de migraciones.

```bash
cp backend/.env.example backend/.env
chmod 600 backend/.env
# Edita backend/.env con tus credenciales

docker compose up -d --build
docker compose logs -f
```

## ☁️ Despliegue 24/7 en la Nube

Consulta [DESPLIEGUE_NUBE.md](DESPLIEGUE_NUBE.md) para Hugging Face Spaces, Koyeb y Docker local.

## ✅ Calidad y Pruebas

```bash
cd backend
PYTHONPATH=. venv/bin/pytest -q
venv/bin/ruff check app tests
venv/bin/mypy
```

El flujo de GitHub Actions (`.github/workflows/ci.yml`) ejecuta lint, type check, compilación y pruebas en cada push y pull request.
