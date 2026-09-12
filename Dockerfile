# Runtime Python ultra-liviano para LibroSync
FROM python:3.11-slim

# Evitar escritura de .pyc y forzar salida inmediata en stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    DATABASE_URL=sqlite+aiosqlite:////app/librosync.db

WORKDIR /app

# Dependencias del sistema mínimas
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias de Python con caché optimizado
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copiar el código fuente y la base de datos viva
COPY backend /app/backend
COPY librosync.db /app/librosync.db

# Iniciar el bot de Telegram en modo servicio puro
CMD ["python", "-m", "app.main"]
