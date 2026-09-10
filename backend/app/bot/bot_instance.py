import logging
from telegram.ext import Application, ApplicationBuilder, CommandHandler, MessageHandler, filters
from app.core.config import settings
from app.bot.handlers import start_handler, document_handler

logger = logging.getLogger(__name__)

_bot_application: Application = None

def get_bot_application() -> Application:
    global _bot_application
    if _bot_application is None:
        _bot_application = (
            ApplicationBuilder()
            .token(settings.TELEGRAM_BOT_TOKEN)
            .build()
        )
        # Registrar handlers
        _bot_application.add_handler(CommandHandler("start", start_handler))
        _bot_application.add_handler(MessageHandler(filters.Document.ALL, document_handler))
        logger.info("Handlers del bot de Telegram registrados exitosamente.")
    return _bot_application
