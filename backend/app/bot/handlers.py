import logging
import re
from datetime import datetime, timezone
from typing import Optional, List

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
from app.models.topic import Topic
from app.models.book import Book
from app.services.telegram_service import get_chat_and_bot_status, move_or_repost_to_topic, ThreadNotFoundError
from app.services.topic_resolver import resolve_or_create_topic, normalize_genre_slug
from app.services.ai_classifier import classify_book_with_gemini

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".epub", ".mobi", ".azw3", ".cbr", ".cbz"}

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
            msg_lines.append("🚀 ¡Motor de Inteligencia Artificial activo! Ya puedes enviar libros sin hashtags ni comandos.")

        await message.reply_text("\n".join(msg_lines), parse_mode="Markdown")


async def set_topic_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando OPCIONAL: /settopic <NombreDelGenero>
    Permite vincular un tema creado manualmente en Telegram a un género específico.
    Se ejecuta DENTRO del tema que se desea mapear.
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    thread_id = getattr(message, "message_thread_id", None)
    if not thread_id:
        await message.reply_text("⚠️ Este comando debe ejecutarse **dentro** del tema que deseas vincular.")
        return

    if not context.args:
        await message.reply_text("Uso: `/settopic <Nombre del Género>` (ejemplo: `/settopic Dark Romance`)", parse_mode="Markdown")
        return

    genre_name = " ".join(context.args).strip().title()

    async with AsyncSessionLocal() as session:
        stmt = select(TelegramLink).where(TelegramLink.chat_id == chat.id)
        res = await session.execute(stmt)
        link = res.scalar_one_or_none()

        if not link:
            await message.reply_text("❌ Este grupo no está vinculado a LibroSync. Vinclalo primero con `/start <codigo>`.")
            return

        target_slug = normalize_genre_slug(genre_name)

        # Buscar todos los topics del chat para limpiar cualquier conflicto de unicidad
        stmt_topics = select(Topic).where(Topic.telegram_link_id == link.id)
        t_res = await session.execute(stmt_topics)
        all_topics = t_res.scalars().all()

        # Eliminar registros viejos que colisionen por thread_id o por género
        for t in all_topics:
            if t.topic_id == thread_id or normalize_genre_slug(t.genre) == target_slug:
                await session.delete(t)

        await session.flush()

        # Insertar el nuevo mapeo limpio y libre de conflictos
        new_t = Topic(
            telegram_link_id=link.id,
            genre=genre_name,
            topic_id=thread_id
        )
        session.add(new_t)
        await session.commit()
        await session.refresh(new_t)

        await message.reply_text(
            f"✅ **¡Tema vinculado exitosamente!**\n\n"
            f"A partir de ahora los libros de **{genre_name}** se archivarán automáticamente en este tema.",
            parse_mode="Markdown"
        )


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Detecta cuando se envía un libro (PDF, EPUB, etc.).
    Utiliza Gemini AI para extraer título, autor y clasificar el género de forma 100% autónoma.
    No requiere hashtags ni comandos por parte del usuario.
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not message.document:
        return

    doc = message.document
    filename = doc.file_name or "libro_desconocido"
    base_raw, ext = clean_filename(filename)

    if f".{ext}" not in SUPPORTED_EXTENSIONS:
        logger.debug(f"Documento ignorado por extensión no soportada: {filename}")
        return

    async with AsyncSessionLocal() as session:
        # 1. Verificar vinculación del chat
        stmt = select(TelegramLink).where(TelegramLink.chat_id == chat.id)
        res = await session.execute(stmt)
        link = res.scalar_one_or_none()

        if not link:
            logger.info(f"Documento recibido en chat no vinculado ({chat.id}). Ignorando.")
            return

        # 2. Consultar lista de géneros ya existentes en este grupo
        stmt_topics = select(Topic).where(Topic.telegram_link_id == link.id)
        topics_res = await session.execute(stmt_topics)
        existing_topics_list = [t.genre for t in topics_res.scalars().all()]

        # 3. Clasificación inteligente con Gemini AI (Zero-friction)
        logger.info(f"Clasificando libro '{filename}' con Gemini AI...")
        classification = await classify_book_with_gemini(
            filename=filename,
            caption=message.caption,
            existing_topics=existing_topics_list
        )

        title = classification["title"]
        author = classification["author"]
        genre = classification["genre"]
        suggested_emoji = classification.get("emoji", "📖")

        current_thread_id = getattr(message, "message_thread_id", None)
        target_message_id = message.message_id
        assigned_topic_id = current_thread_id

        # 4. Auto-organización en supergrupos con temas
        if link.forum_enabled:
            topic_id = await resolve_or_create_topic(
                session=session,
                bot=context.bot,
                telegram_link=link,
                genre=genre,
                suggested_emoji=suggested_emoji
            )
            assigned_topic_id = topic_id

            # Si el archivo se subió en el General o en un topic distinto, moverlo/copiarlo al topic del género
            if topic_id and current_thread_id != topic_id:
                try:
                    reposted_id = await move_or_repost_to_topic(
                        bot=context.bot,
                        chat_id=chat.id,
                        message_id=message.message_id,
                        topic_id=topic_id,
                        delete_original=link.bot_is_admin
                    )
                    if reposted_id:
                        target_message_id = reposted_id
                except ThreadNotFoundError:
                    # El topic en Telegram fue borrado por un usuario. Auto-recuperación con Emoji:
                    logger.warning(f"Topic {topic_id} fue eliminado en Telegram. Auto-creando nuevo topic para '{genre}'...")
                    from app.services.topic_resolver import delete_topic_by_thread_id
                    from app.services.ai_classifier import get_genre_emoji
                    await delete_topic_by_thread_id(session, link.id, topic_id)

                    emoji = get_genre_emoji(genre, suggested_emoji)
                    new_created = await context.bot.create_forum_topic(chat_id=chat.id, name=f"{emoji} {genre}"[:128])
                    new_topic = Topic(telegram_link_id=link.id, genre=genre, topic_id=new_created.message_thread_id)
                    session.add(new_topic)
                    await session.commit()
                    await session.refresh(new_topic)

                    assigned_topic_id = new_created.message_thread_id
                    reposted_id = await move_or_repost_to_topic(
                        bot=context.bot,
                        chat_id=chat.id,
                        message_id=message.message_id,
                        topic_id=new_created.message_thread_id,
                        delete_original=link.bot_is_admin
                    )
                    if reposted_id:
                        target_message_id = reposted_id

        # 5. Registrar en base de datos
        new_book = Book(
            user_id=link.user_id,
            title=title,
            author=author,
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

        logger.info(f"Libro registrado: '{new_book.title}' por '{new_book.author}' -> Género: {new_book.genre}")

        # 6. Notificación visual en el tema de destino para feedback inmediato
        if assigned_topic_id:
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=assigned_topic_id,
                    text=f"📚 **Libro sincronizado y archivado**\n\n"
                         f"📖 **Título:** {title}\n"
                         f"✍️ **Autor:** {author}\n"
                         f"🏷️ **Género:** {genre}",
                    parse_mode="Markdown"
                )
            except Exception as notify_err:
                logger.debug(f"No se pudo enviar mensaje de confirmación: {notify_err}")
