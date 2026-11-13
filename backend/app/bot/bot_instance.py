from __future__ import annotations

import logging
from telegram import (
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllChatAdministrators,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)
from app.core.config import settings
from app.bot.handlers import (
    start_handler,
    document_handler,
    set_topic_handler,
    catalog_handler,
    catalog_callback_handler,
    search_handler,
    search_callback_handler,
    download_command_handler,
    download_callback_handler,
    download_page_callback_handler,
    topics_list_handler,
    topics_callback_handler,
    topic_index_handler,
    topic_index_callback_handler,
    register_reply_handler,
    rename_book_handler,
    help_handler,
    chat_member_update_handler,
    sync_handler,
    reorganize_command_handler,
    info_handler,
    buddy_read_handler,
    my_books_handler,
    progress_command_handler,
    buddy_read_callback_handler,
    reading_state_callback_handler,
    deduplicate_command_handler,
    lost_book_callback_handler,
    setup_mode_callback_handler,
    code_exp_callback_handler,
    text_message_handler,
)


logger = logging.getLogger(__name__)

_bot_application: Application = None

async def setup_bot_commands(bot):
    """Registra el menú de comandos en Telegram para autocompletado nativo en chats privados, grupos y administradores."""
    try:
        commands = [
            BotCommand("buscar", "Buscar libros por título o autor"),
            BotCommand("libros", "Ver catálogo de libros disponibles"),
            BotCommand("temas", "Ver temas y géneros disponibles"),
            BotCommand("indice", "Publicar índice de este tema"),
            BotCommand("descargar", "Buscar y descargar libros a la biblioteca"),
            BotCommand("leerjuntos", "Iniciar o unirse a una lectura conjunta"),
            BotCommand("mislibros", "Mi perfil: leídos, leyendo, progreso y conjuntas"),
            BotCommand("progreso", "Actualizar mi porcentaje de lectura actual"),
            BotCommand("info", "Ficha del libro, estante y acciones"),
            BotCommand("registrar", "Registrar libro respondiendo a su mensaje"),
            BotCommand("reorganizar", "Mover libros fuera de tema a su estante"),
            BotCommand("deduplicar", "Eliminar libros duplicados automáticamente"),
            BotCommand("sincronizar", "Mantenimiento general de la biblioteca"),
            BotCommand("help", "Mostrar ayuda y comandos disponibles"),
        ]
        await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
        await bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())
        await bot.set_my_commands(commands, scope=BotCommandScopeAllGroupChats())
        await bot.set_my_commands(commands, scope=BotCommandScopeAllChatAdministrators())
        logger.info("Menú de comandos de Telegram configurado con éxito en todos los ámbitos.")
    except Exception as e:
        logger.warning(f"No se pudieron configurar los comandos de Telegram en BotFather: {e}")

def get_bot_application() -> Application:
    global _bot_application
    if _bot_application is None:
        _bot_application = (
            ApplicationBuilder()
            .token(settings.TELEGRAM_BOT_TOKEN)
            .connect_timeout(30.0)
            .read_timeout(120.0)
            .write_timeout(120.0)
            .pool_timeout(60.0)
            .build()
        )
        # Registrar comandos
        _bot_application.add_handler(CommandHandler(["start", "enlazar", "vincular"], start_handler))
        _bot_application.add_handler(CommandHandler("help", help_handler))
        _bot_application.add_handler(CommandHandler(["leerjuntos", "conjunta", "buddyread"], buddy_read_handler))
        _bot_application.add_handler(CommandHandler(["mislibros", "perfil", "estantes"], my_books_handler))
        _bot_application.add_handler(CommandHandler(["progreso", "avance"], progress_command_handler))
        _bot_application.add_handler(CommandHandler(["info", "detalle", "saga"], info_handler))
        _bot_application.add_handler(CommandHandler(["descargar", "pedir", "download"], download_command_handler))
        _bot_application.add_handler(CommandHandler(["buscar", "search", "encontrar"], search_handler))
        _bot_application.add_handler(CommandHandler("libros", catalog_handler))
        _bot_application.add_handler(CommandHandler("catalogo", catalog_handler))
        _bot_application.add_handler(CommandHandler("biblioteca", catalog_handler))
        _bot_application.add_handler(CommandHandler("temas", topics_list_handler))
        _bot_application.add_handler(CommandHandler("indice", topic_index_handler))
        _bot_application.add_handler(CommandHandler(["deduplicar", "dedup"], deduplicate_command_handler))
        _bot_application.add_handler(CommandHandler(["sincronizar", "limpiar", "sync"], sync_handler))
        _bot_application.add_handler(CommandHandler(["reorganizar", "organizar", "mover"], reorganize_command_handler))
        _bot_application.add_handler(CommandHandler("registrar", register_reply_handler))
        _bot_application.add_handler(CommandHandler("indexar", register_reply_handler))
        _bot_application.add_handler(CommandHandler(["renombrar", "editar"], rename_book_handler))
        _bot_application.add_handler(CommandHandler("settopic", set_topic_handler))

        # Callback queries (paginación e interactividad)
        _bot_application.add_handler(CallbackQueryHandler(catalog_callback_handler, pattern="^catalog:"))
        _bot_application.add_handler(CallbackQueryHandler(topic_index_callback_handler, pattern="^tindex:"))
        _bot_application.add_handler(CallbackQueryHandler(topics_callback_handler, pattern="^topics:"))
        _bot_application.add_handler(CallbackQueryHandler(search_callback_handler, pattern="^search:"))
        _bot_application.add_handler(CallbackQueryHandler(download_page_callback_handler, pattern="^dlp:"))
        _bot_application.add_handler(CallbackQueryHandler(download_callback_handler, pattern="^dl:"))
        _bot_application.add_handler(CallbackQueryHandler(buddy_read_callback_handler, pattern="^br:"))
        _bot_application.add_handler(CallbackQueryHandler(reading_state_callback_handler, pattern="^rs:"))
        _bot_application.add_handler(CallbackQueryHandler(lost_book_callback_handler, pattern="^rec:"))
        _bot_application.add_handler(CallbackQueryHandler(setup_mode_callback_handler, pattern="^setup_mode:"))
        _bot_application.add_handler(CallbackQueryHandler(code_exp_callback_handler, pattern="^code_exp:"))

        # Ingesta de libros
        _bot_application.add_handler(MessageHandler(filters.Document.ALL, document_handler))

        # Respuesta conversacional tras comandos sin argumentos (/descargar, /buscar, /info, /leerjuntos)
        _bot_application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

        # Evento de unión o promoción del bot en grupos
        _bot_application.add_handler(ChatMemberHandler(chat_member_update_handler, ChatMemberHandler.MY_CHAT_MEMBER))

        # Gestor de errores global para prevenir caídas silenciosas
        async def bot_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
            err = context.error
            logger.error(f"Excepción en bot de Telegram: {err}", exc_info=err)
            from telegram.error import Conflict
            if isinstance(err, Conflict):
                logger.warning("⚠️ Telegram 409 Conflict detectado en handler. El watchdog supervisará la reconexión.")

        _bot_application.add_error_handler(bot_error_handler)

        logger.info("Todos los handlers del bot de Telegram registrados exitosamente.")
    return _bot_application

