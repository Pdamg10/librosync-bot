import logging
import re
from datetime import datetime, timezone
from typing import Optional

from telegram import Update
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.link_code import LinkCode
from app.models.telegram_link import TelegramLink
from app.models.book import Book
from app.models.topic import Topic
from app.services.telegram_service import get_chat_and_bot_status, move_or_repost_to_topic
from app.services.topic_resolver import resolve_or_create_topic

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".epub", ".mobi", ".azw3", ".cbr", ".cbz"}

def extract_genre_from_caption(caption: Optional[str]) -> Optional[str]:
    """Extrae género si viene como hashtag (ej: #Romance, #CienciaFiccion)"""
    if not caption:
        return None
    hashtags = re.findall(r"#(\w+)", caption)
    if hashtags:
        # Tomar el primer hashtag como género
        return hashtags[0].replace("_", " ").title()
    return None

def clean_filename(filename: str) -> tuple[str, str]:
    """Separa el nombre base y la extensión limpia"""
    parts = filename.rsplit(".", 1)
    if len(parts) == 2:
        return parts[0], parts[1].lower()
    return filename, "unknown"


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Maneja el comando /start [codigo_vinculacion]
    Permite vincular grupos, canales o chats privados con la cuenta de LibroSync.
    """
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not message or not chat:
        return

    args = context.args
    if not args:
        if chat.type == "private":
            await message.reply_text(
                "👋 **¡Hola! Soy Griffin, el bot de LibroSync.**\n\n"
                "Para sincronizar tu biblioteca con Telegram:\n"
                "1. Añádeme a tu grupo (con **Temas/Topics** activados) o canal.\n"
                "2. Hazme administrador con permiso de **'Administrar temas'**.\n"
                "3. En la app móvil, pulsa en **'Vincular Telegram'** y usa el enlace proporcionado.",
                parse_mode="Markdown"
            )
        else:
            await message.reply_text(
                "ℹ️ Para vincular este chat con tu cuenta de LibroSync, envía:\n"
                "`/start <codigo_de_vinculacion>`\n\n"
                "(Obtén el código en tu app móvil LibroSync)",
                parse_mode="Markdown"
            )
        return

    code_str = args[0].strip()

    async with AsyncSessionLocal() as session:
        # 1. Validar código
        stmt = select(LinkCode).where(
            LinkCode.code == code_str,
            LinkCode.used == False,
            LinkCode.expires_at > datetime.now(timezone.utc)
        )
        res = await session.execute(stmt)
        link_code = res.scalar_one_or_none()

        if not link_code:
            await message.reply_text(
                "⚠️ **Código inválido o expirado.**\n"
                "Por favor genera un nuevo código de vinculación desde la app.",
                parse_mode="Markdown"
            )
            return

        # 2. Obtener estado e inspección del chat
        bot = context.bot
        try:
            status_info = await get_chat_and_bot_status(bot, chat.id)
        except Exception as e:
            await message.reply_text(f"❌ Error al consultar información del chat: {e}")
            return

        chat_type_str = "group_forum" if status_info["forum_enabled"] else status_info["chat_type"]

        # 3. Buscar si el link ya existía para actualizarlo o crearlo
        stmt_link = select(TelegramLink).where(TelegramLink.chat_id == chat.id)
        res_link = await session.execute(stmt_link)
        existing_link = res_link.scalar_one_or_none()

        if existing_link:
            existing_link.user_id = link_code.user_id
            existing_link.chat_type = chat_type_str
            existing_link.chat_title = status_info["chat_title"]
            existing_link.bot_is_admin = status_info["bot_is_admin"]
            existing_link.forum_enabled = status_info["forum_enabled"]
            existing_link.linked_at = datetime.now(timezone.utc)
        else:
            new_link = TelegramLink(
                user_id=link_code.user_id,
                chat_id=chat.id,
                chat_type=chat_type_str,
                chat_title=status_info["chat_title"],
                bot_is_admin=status_info["bot_is_admin"],
                forum_enabled=status_info["forum_enabled"]
            )
            session.add(new_link)

        # 4. Quemar código de vinculación
        link_code.used = True
        await session.commit()

        # 5. Respuesta informativa según configuración
        msg_lines = [
            f"🎉 **¡Chat '{status_info['chat_title']}' vinculado exitosamente a LibroSync!**\n",
            f"• **Tipo:** `{chat_type_str}`",
            f"• **Temas (Forum):** {'✅ Activado' if status_info['forum_enabled'] else '❌ Desactivado'}",
            f"• **Bot Admin:** {'✅ Sí' if status_info['bot_is_admin'] else '❌ No'}",
            f"• **Permiso Manage Topics:** {'✅ Sí' if status_info['can_manage_topics'] else '❌ No'}\n"
        ]

        if not status_info["bot_is_admin"] or not status_info.get("can_manage_topics"):
            msg_lines.append(
                "⚠️ **Nota:** Para crear y organizar libros en temas automáticamente, "
                "asegúrate de hacer al bot administrador con el permiso **'Administrar temas'**."
            )
        else:
            msg_lines.append("🚀 Todo configurado al 100%. ¡Ya puedes enviar libros!")

        await message.reply_text("\n".join(msg_lines), parse_mode="Markdown")


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Detecta cuando se envía un archivo / documento (libro).
    Lo clasifica, resuelve el topic correspondiente y lo registra en la base de datos.
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not message.document:
        return

    doc = message.document
    filename = doc.file_name or "libro_sin_nombre"
    base_title, ext = clean_filename(filename)

    if f".{ext}" not in SUPPORTED_EXTENSIONS:
        logger.debug(f"Documento ignorado por extensión no soportada: {filename}")
        return

    async with AsyncSessionLocal() as session:
        # Verificar si este chat está vinculado a LibroSync
        stmt = select(TelegramLink).where(TelegramLink.chat_id == chat.id)
        res = await session.execute(stmt)
        link = res.scalar_one_or_none()

        if not link:
            logger.info(f"Documento recibido en chat no vinculado ({chat.id}). Ignorando.")
            return

        # Determinar género
        # 1. Por hashtag en caption
        genre = extract_genre_from_caption(message.caption)

        # 2. Si se subió dentro de un topic específico existente
        current_thread_id = getattr(message, "message_thread_id", None)
        if not genre and current_thread_id:
            stmt_topic = select(Topic).where(
                Topic.telegram_link_id == link.id,
                Topic.topic_id == current_thread_id
            )
            topic_res = await session.execute(stmt_topic)
            existing_topic = topic_res.scalar_one_or_none()
            if existing_topic:
                genre = existing_topic.genre

        # Fallback a "General"
        if not genre:
            genre = "General"

        target_message_id = message.message_id
        assigned_topic_id = current_thread_id

        # Auto-organización en supergrupos con topics
        if link.forum_enabled:
            topic_id = await resolve_or_create_topic(session, context.bot, link, genre)
            assigned_topic_id = topic_id

            # Si se subió en el General o en un topic distinto, moverlo/copiarlo al topic del género
            if topic_id and current_thread_id != topic_id:
                reposted_id = await move_or_repost_to_topic(
                    bot=context.bot,
                    chat_id=chat.id,
                    message_id=message.message_id,
                    topic_id=topic_id,
                    delete_original=link.bot_is_admin  # Solo borrar si somos admin
                )
                if reposted_id:
                    target_message_id = reposted_id

        # Registrar libro en la base de datos
        new_book = Book(
            user_id=link.user_id,
            title=base_title.replace("_", " ").title(),
            author="Desconocido",
            genre=genre,
            source="telegram",
            telegram_link_id=link.id,
            telegram_message_id=target_message_id,
            telegram_file_id=doc.file_id,
            file_format=ext,
            reading_progress=0.0
        )
        session.add(new_book)
        await session.commit()
        await session.refresh(new_book)

        logger.info(f"Libro registrado: '{new_book.title}' (ID {new_book.id}, Género: {new_book.genre})")
