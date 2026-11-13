import asyncio
import logging
import signal
from app.core.config import settings
from app.core.database import init_db
from app.core.logging_config import configure_logging
from app.bot.bot_instance import get_bot_application, setup_bot_commands

configure_logging()
logger = logging.getLogger("librosync")


_bot_connected = False


async def handle_health_check(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Responde 200 OK a las sondas HTTP de salud de Hugging Face Spaces / Docker / Koyeb / Render."""
    try:
        await reader.read(1024)
        body = (
            f'{{"status":"ok","service":"librosync-bot","telegram_connected":{str(_bot_connected).lower()},'
            f'"bot_username":"{settings.TELEGRAM_BOT_USERNAME}"}}'
        ).encode("utf-8")
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json; charset=utf-8\r\n"
            b"Access-Control-Allow-Origin: *\r\n"
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


async def keep_alive_task(stop_event: asyncio.Event, target_url: str):
    """Mantiene despierto el contenedor en plataformas con sleep por inactividad (ej. Render Free)."""
    logger.info(f"⏰ Keep-alive pinger activo hacia: {target_url}")
    await asyncio.sleep(60)
    while not stop_event.is_set():
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(target_url)
                logger.info(f"📡 Ping keep-alive enviado a {target_url} (HTTP {res.status_code})")
        except Exception as e:
            logger.warning(f"Aviso en ping keep-alive hacia {target_url}: {e}")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=540.0)  # Cada 9 minutos
        except asyncio.TimeoutError:
            pass


async def run_bot():
    """Servicio asíncrono puro de Python para el Bot de Telegram Griffin / LibroSync."""
    global _bot_connected

    if settings.ENABLE_NETWORK_PATCH:
        from app.core.network_patch import apply_network_patches
        apply_network_patches()

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

    # 2. Configurar señales de parada temprana
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):
            pass

    # 3. Lanzar worker keep-alive si hay URL pública disponible (ej. Render / Spaces)
    keep_alive_handle = None
    if settings.KEEP_ALIVE_URL:
        keep_alive_handle = asyncio.create_task(keep_alive_task(stop_event, settings.KEEP_ALIVE_URL))

    # 4. Inicializar Bot de Telegram (Polling resiliente con reintento infinito)
    bot_app = get_bot_application()
    logger.info("Iniciando bot de Telegram (Griffin / LibroSync) en modo servicio continuo...")

    attempt = 0
    while not stop_event.is_set():
        attempt += 1
        try:
            if not getattr(bot_app, "_initialized", False):
                await bot_app.initialize()
            if not getattr(bot_app, "_running", False):
                await bot_app.start()

            # Descartar webhooks residuales sin purgar mensajes en cola
            try:
                await bot_app.bot.delete_webhook(drop_pending_updates=False)
            except Exception:
                pass

            await setup_bot_commands(bot_app.bot)
            await bot_app.updater.start_polling(drop_pending_updates=False)
            _bot_connected = True
            logger.info("✅ Bot de Telegram en línea y escuchando actualizaciones.")
            break
        except Exception as e:
            err_str = str(e).lower()
            if "conflict" in err_str:
                logger.warning(
                    f"⚠️ Telegram 409 Conflict detectado (otra instancia del bot tiene el token). "
                    f"Esperando 5s para reintentar (intento #{attempt})..."
                )
                wait_sec = 5
            else:
                wait_sec = min(30, 4 + attempt * 2)
                logger.warning(f"Intento #{attempt} para iniciar bot de Telegram falló: {e}. Reintentando en {wait_sec}s...")

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=wait_sec)
            except asyncio.TimeoutError:
                pass

    # 5. Watchdog Activo: Mantener servicio vivo y revivir polling automáticamente
    try:
        while not stop_event.is_set():
            try:
                if bot_app.updater and not bot_app.updater.running and not stop_event.is_set():
                    _bot_connected = False
                    logger.warning("⚠️ Updater de Telegram detenido inesperadamente. Reiniciando polling en 5s...")
                    await asyncio.sleep(5)
                    if not stop_event.is_set():
                        try:
                            await bot_app.bot.delete_webhook(drop_pending_updates=False)
                            await bot_app.updater.start_polling(drop_pending_updates=False)
                            _bot_connected = True
                            logger.info("✅ Polling de Telegram restablecido exitosamente por watchdog.")
                        except Exception as restart_err:
                            logger.warning(f"Reintento de polling fallido: {restart_err}")
                elif bot_app.updater and bot_app.updater.running:
                    _bot_connected = True
            except Exception as watchdog_err:
                logger.error(f"Error en watchdog del bot: {watchdog_err}")

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
    finally:
        logger.info("Deteniendo bot de Telegram de forma controlada...")
        _bot_connected = False
        if keep_alive_handle and not keep_alive_handle.done():
            keep_alive_handle.cancel()
        if bot_app.updater and bot_app.updater.running:
            await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()
        if health_server:
            health_server.close()
            await health_server.wait_closed()
        logger.info("Bot de Telegram detenido limpiamente.")


def main():
    if not settings.TELEGRAM_BOT_TOKEN.strip():
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN no está configurado. Define la variable de entorno "
            "o crea backend/.env antes de iniciar el bot."
        )
    if settings.is_production and settings.SECRET_KEY.startswith("librosync-"):
        logger.warning("SECRET_KEY insegura en producción; define una clave aleatoria.")
    try:
        asyncio.run(run_bot())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Servicio detenido por el usuario.")


if __name__ == "__main__":
    main()
