# Runtime Python ligero para LibroSync
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    DATABASE_URL=sqlite+aiosqlite:////app/data/librosync.db \
    SEED_DATABASE_PATH=/app/seed/librosync.db \
    STORAGE_DIR=/app/data/storage

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system librosync \
    && useradd --system --gid librosync --home-dir /app --shell /usr/sbin/nologin librosync

# Dependencias fijadas para builds reproducibles.
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/backend/requirements.txt

# Código de la aplicación y semilla inicial del catálogo (sin .env ni tests).
COPY --chown=librosync:librosync backend/app /app/backend/app
COPY --chown=librosync:librosync librosync.db /app/seed/librosync.db
RUN mkdir -p /app/data/storage /app/seed && chown -R librosync:librosync /app/data /app/seed

USER librosync

EXPOSE 8000 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/' % os.getenv('API_PORT','8000'), timeout=3).read()" || exit 1

# Iniciar el bot de Telegram en modo servicio puro
CMD ["python", "-m", "app.main"]
