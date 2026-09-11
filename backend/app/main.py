import app.core.network_patch

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.api.router import api_router
from app.bot.bot_instance import get_bot_application

logging.basicConfig(
    level=logging.INFO if settings.DEBUG else logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("librosync")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Inicializar Tablas en la Base de Datos
    logger.info("Inicializando esquemas de Base de Datos...")
    await init_db()
    logger.info("Base de datos lista.")

    # 2. Inicializar y Arrancar Bot de Telegram (Polling en background)
    from app.bot.bot_instance import get_bot_application, setup_bot_commands
    import asyncio
    bot_app = get_bot_application()
    logger.info("Iniciando bot de Telegram (Polling)...")
    for attempt in range(3):
        try:
            await bot_app.initialize()
            await bot_app.start()
            await setup_bot_commands(bot_app.bot)
            await bot_app.updater.start_polling(drop_pending_updates=True)
            logger.info("Bot de Telegram en línea y escuchando actualizaciones.")
            break
        except Exception as e:
            logger.warning(f"Intento {attempt + 1}/3 para iniciar el bot de Telegram falló: {e}. Reintentando en 3s...")
            await asyncio.sleep(3)

    try:
        yield
    finally:
        # 3. Graceful shutdown
        logger.info("Deteniendo bot de Telegram...")
        if bot_app.updater and bot_app.updater.running:
            await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()
        logger.info("Bot de Telegram detenido limpiamente.")


app = FastAPI(
    title="LibroSync API",
    version="1.0.0",
    description="Backend y Bot de Telegram para Biblioteca Digital organizada en Topics",
    lifespan=lifespan
)

# CORS middleware para React Native / Expo
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

@app.get("/")
async def root():
    return {
        "app": "LibroSync API",
        "status": "online",
        "bot_username": settings.TELEGRAM_BOT_USERNAME,
        "docs_url": "/docs"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
