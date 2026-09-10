import logging
from telegram import BotCommand
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from app.core.config import settings
from app.bot.handlers import (
    start_handler,
    document_handler,
    set_topic_handler,
    catalog_handler,
    catalog_callback_handler,
    topics_list_handler,
    topic_index_handler,
    register_reply_handler,
    help_handler,
)

logger = logging.getLogger(__name__)

_bot_application: Application = None

async def setup_bot_commands(bot):
    """Registra el menú de comandos en Telegram para autocompletado nativo."""
    try:
        commands = [
            BotCommand("libros", "Ver catálogo de libros disponibles"),
            BotCommand("temas", "Ver todos los temas y géneros"),
            BotCommand("indice", "Publicar índice de libros en este tema"),
            BotCommand("registrar", "Registrar un libro respondiendo a su mensaje"),
            BotCommand("settopic", "Vincular este tema a un género"),
            BotCommand("help", "Mostrar ayuda y comandos disponibles"),
        ]
        await bot.set_my_commands(commands)
        logger.info("Menú de comandos de Telegram configurado con éxito.")
    except Exception as e:
        logger.warning(f"No se pudieron configurar los comandos de Telegram en BotFather: {e}")

def get_bot_application() -> Application:
    global _bot_application
    if _bot_application is None:
        _bot_application = (
            ApplicationBuilder()
            .token(settings.TELEGRAM_BOT_TOKEN)
            .build()
        )
        # Registrar comandos
        _bot_application.add_handler(CommandHandler("start", start_handler))
        _bot_application.add_handler(CommandHandler("help", help_handler))
        _bot_application.add_handler(CommandHandler("libros", catalog_handler))
        _bot_application.add_handler(CommandHandler("catalogo", catalog_handler))
        _bot_application.add_handler(CommandHandler("biblioteca", catalog_handler))
        _bot_application.add_handler(CommandHandler("temas", topics_list_handler))
        _bot_application.add_handler(CommandHandler("indice", topic_index_handler))
        _bot_application.add_handler(CommandHandler("registrar", register_reply_handler))
        _bot_application.add_handler(CommandHandler("indexar", register_reply_handler))
        _bot_application.add_handler(CommandHandler("settopic", set_topic_handler))

        # Callback queries (paginación interactiva)
        _bot_application.add_handler(CallbackQueryHandler(catalog_callback_handler, pattern="^catalog:"))

        # Ingesta de libros
        _bot_application.add_handler(MessageHandler(filters.Document.ALL, document_handler))

        logger.info("Todos los handlers del bot de Telegram registrados exitosamente.")
    return _bot_application
