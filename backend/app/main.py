import app.core.network_patch

import asyncio
import logging
import signal
from app.core.config import settings
from app.core.database import init_db
from app.bot.bot_instance import get_bot_application, setup_bot_commands

logging.basicConfig(
    level=logging.INFO if settings.DEBUG else logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("librosync")


async def handle_health_check(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Responde 200 OK a las sondas HTTP de salud de Hugging Face Spaces / Docker / Koyeb."""
    try:
        await reader.read(1024)
        body = b'{"status":"ok","service":"librosync-bot"}'
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"Connection: close\r\n\r\n" + body
        )
        writer.write(response)
        await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def run_bot():
    """Servicio asíncrono puro de Python para el Bot de Telegram Griffin / LibroSync."""
    # 0. Iniciar servidor HTTP ligero para health check en la nube
    health_server = None
    try:
        health_server = await asyncio.start_server(
            handle_health_check, settings.API_HOST, settings.API_PORT
        )
        logger.info(f"✅ Health-check HTTP activo en {settings.API_HOST}:{settings.API_PORT}")
    except Exception as e:
        logger.warning(f"No se pudo iniciar el health-check HTTP en el puerto {settings.API_PORT}: {e}")

    # 1. Inicializar Tablas en la Base de Datos
    logger.info("Inicializando esquemas de Base de Datos...")
    await init_db()
    logger.info("Base de datos SQLite sincronizada y lista.")

    # 2. Inicializar Bot de Telegram (Polling)
    bot_app = get_bot_application()
    logger.info("Iniciando bot de Telegram (Griffin / LibroSync) en modo servicio puro...")

    started = False
    for attempt in range(3):
        try:
            await bot_app.initialize()
            await bot_app.start()
            await setup_bot_commands(bot_app.bot)
            await bot_app.updater.start_polling(drop_pending_updates=False)
            logger.info("✅ Bot de Telegram en línea y escuchando actualizaciones.")
            started = True
            break
        except Exception as e:
            logger.warning(f"Intento {attempt + 1}/3 para iniciar el bot de Telegram falló: {e}. Reintentando en 3s...")
            await asyncio.sleep(3)

    if not started:
        logger.error("No se pudo iniciar el bot de Telegram tras 3 intentos. Abortando.")
        if health_server:
            health_server.close()
            await health_server.wait_closed()
        return

    # 3. Mantener servicio vivo y gestionar señales de parada (SIGINT, SIGTERM)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):
            pass

    try:
        await stop_event.wait()
    finally:
        logger.info("Deteniendo bot de Telegram de forma controlada...")
        if bot_app.updater and bot_app.updater.running:
            await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()
        if health_server:
            health_server.close()
            await health_server.wait_closed()
        logger.info("Bot de Telegram detenido limpiamente.")


def main():
    try:
        asyncio.run(run_bot())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Servicio detenido por el usuario.")


if __name__ == "__main__":
    main()
