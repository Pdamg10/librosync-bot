import logging
import re
import html
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.link_code import LinkCode
from app.models.telegram_link import TelegramLink
from app.models.topic import Topic
from app.models.book import Book
from app.models.reading import ReadingState, BuddyRead, BuddyReadMember
from app.services.telegram_service import get_chat_and_bot_status, move_or_repost_to_topic, ThreadNotFoundError
from app.services.topic_resolver import resolve_or_create_topic, normalize_genre_slug, delete_topic_by_thread_id
from app.services.ai_classifier import classify_book_with_gemini, get_genre_emoji
from app.services.series_formatter import format_book_full_description, enrich_book_series_if_needed

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".epub", ".mobi", ".azw3", ".cbr", ".cbz"}

def clean_filename(filename: str) -> tuple[str, str]:
    """Separa el nombre base y la extensión limpia"""
    parts = filename.rsplit(".", 1)
    if len(parts) == 2:
        return parts[0], parts[1].lower()
    return filename, "unknown"


async def _get_or_create_link(bot, session, chat_id: int) -> Optional[TelegramLink]:
    """Obtiene el vínculo existente para un chat o lo auto-vincula de forma transparente."""
    stmt = select(TelegramLink).where(TelegramLink.chat_id == chat_id)
    res = await session.execute(stmt)
    link = res.scalar_one_or_none()
    if not link:
        try:
            status_info = await get_chat_and_bot_status(bot, chat_id)
            chat_type_str = "group_forum" if status_info["forum_enabled"] else status_info["chat_type"]
            link = TelegramLink(
                user_id=1,
                chat_id=chat_id,
                chat_type=chat_type_str,
                chat_title=status_info["chat_title"],
                bot_is_admin=status_info["bot_is_admin"],
                forum_enabled=status_info["forum_enabled"]
            )
            session.add(link)
            await session.commit()
            await session.refresh(link)
        except Exception as err:
            logger.warning(f"No se pudo auto-vincular chat {chat_id}: {err}")
            return None
    return link


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
                "👋 <b>¡Hola! Soy el asistente de LibroSync / Anaquel.</b>\n\n"
                "Para sincronizar tu biblioteca con Telegram:\n"
                "1. Añádeme a tu grupo (con <b>Temas/Topics</b> activados) o canal.\n"
                "2. Hazme administrador con permiso de <b>'Administrar temas'</b>.\n"
                "3. En la app móvil, pulsa en <b>'Vincular Telegram'</b> y usa el enlace proporcionado.",
                parse_mode="HTML"
            )
        else:
            await message.reply_text(
                "ℹ️ Para vincular este chat con tu cuenta de LibroSync, envía:\n"
                "<code>/start &lt;codigo_de_vinculacion&gt;</code>\n\n"
                "(Obtén el código en tu app móvil LibroSync)",
                parse_mode="HTML"
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
                "⚠️ <b>Código inválido o expirado.</b>\n"
                "Por favor genera un nuevo código de vinculación desde la app.",
                parse_mode="HTML"
            )
            return

        # 2. Obtener estado e inspección del chat
        bot = context.bot
        try:
            status_info = await get_chat_and_bot_status(bot, chat.id)
        except Exception as e:
            await message.reply_text(f"❌ Error al consultar información del chat: {html.escape(str(e))}", parse_mode="HTML")
            return

        chat_type_str = "group_forum" if status_info["forum_enabled"] else status_info["chat_type"]

        # 3. Buscar si el link ya existía para actualizarlo o crearlo
        stmt_link = select(TelegramLink).where(TelegramLink.chat_id == chat.id)
        res_link = await session.execute(stmt_link)
        existing_link = res_link.scalar_one_or_none()

        safe_title = html.escape(status_info["chat_title"])

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
            f"🎉 <b>¡Chat '{safe_title}' vinculado exitosamente a LibroSync!</b>\n",
            f"• <b>Tipo:</b> <code>{chat_type_str}</code>",
            f"• <b>Temas (Forum):</b> {'✅ Activado' if status_info['forum_enabled'] else '❌ Desactivado'}",
            f"• <b>Bot Admin:</b> {'✅ Sí' if status_info['bot_is_admin'] else '❌ No'}",
            f"• <b>Permiso Manage Topics:</b> {'✅ Sí' if status_info['can_manage_topics'] else '❌ No'}\n"
        ]

        if not status_info["bot_is_admin"] or not status_info.get("can_manage_topics"):
            msg_lines.append(
                "⚠️ <b>Nota:</b> Para crear y organizar libros en temas automáticamente, "
                "asegúrate de hacer al bot administrador con el permiso <b>'Administrar temas'</b>."
            )
        else:
            msg_lines.append("🚀 ¡Motor de Inteligencia Artificial activo! Ya puedes enviar libros sin hashtags ni comandos.")

        await message.reply_text("\n".join(msg_lines), parse_mode="HTML")


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
        await message.reply_text("⚠️ Este comando debe ejecutarse <b>dentro</b> del tema que deseas vincular.", parse_mode="HTML")
        return

    if not context.args:
        await message.reply_text("Uso: <code>/settopic &lt;Nombre del Género&gt;</code> (ejemplo: <code>/settopic Dark Romance</code>)", parse_mode="HTML")
        return

    genre_name = " ".join(context.args).strip().title()

    async with AsyncSessionLocal() as session:
        link = await _get_or_create_link(context.bot, session, chat.id)
        if not link:
            await message.reply_text("❌ Este grupo no está vinculado a LibroSync.", parse_mode="HTML")
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

        safe_genre = html.escape(genre_name)
        await message.reply_text(
            f"✅ <b>¡Tema vinculado exitosamente!</b>\n\n"
            f"A partir de ahora los libros de <b>{safe_genre}</b> se archivarán automáticamente en este tema.",
            parse_mode="HTML"
        )


from app.services.book_processor import (
    process_book_message,
    get_chat_lock,
    clean_filename,
    SUPPORTED_EXTENSIONS
)

_media_group_batches: Dict[str, dict] = {}


async def _process_media_group_batch(mg_id: str, context: ContextTypes.DEFAULT_TYPE):
    """Procesa un lote completo de libros enviados simultáneamente (álbum de Telegram)."""
    batch = _media_group_batches.pop(mg_id, None)
    if not batch:
        return

    messages = batch["messages"]
    chat = batch["chat"]
    thread_id = batch["thread_id"]
    total = len(messages)
    import html

    status_msg = None
    try:
        status_msg = await context.bot.send_message(
            chat_id=chat.id,
            message_thread_id=thread_id,
            text=f"📦 <b>Detectado lote de {total} libros.</b> Procesando y organizando estantes con IA...",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(f"No se pudo enviar mensaje inicial de lote: {e}")

    results = []
    async with get_chat_lock(chat.id):
        async with AsyncSessionLocal() as session:
            stmt = select(TelegramLink).where(TelegramLink.chat_id == chat.id)
            res = await session.execute(stmt)
            link = res.scalar_one_or_none()

            if not link:
                try:
                    status_info = await get_chat_and_bot_status(context.bot, chat.id)
                    chat_type_str = "group_forum" if status_info["forum_enabled"] else status_info["chat_type"]
                    link = TelegramLink(
                        user_id=1,
                        chat_id=chat.id,
                        chat_type=chat_type_str,
                        chat_title=status_info["chat_title"],
                        bot_is_admin=status_info["bot_is_admin"],
                        forum_enabled=status_info["forum_enabled"]
                    )
                    session.add(link)
                    await session.commit()
                    await session.refresh(link)
                except Exception as autolink_err:
                    logger.error(f"Error auto-vinculando chat {chat.id}: {autolink_err}")
                    return

            for i, msg in enumerate(messages, start=1):
                try:
                    res_dict = await process_book_message(
                        bot=context.bot,
                        session=session,
                        link=link,
                        chat_id=chat.id,
                        message=msg,
                        delete_original=link.bot_is_admin
                    )
                    results.append(res_dict)
                except Exception as book_err:
                    logger.error(f"Error procesando libro {i}/{total} en lote: {book_err}", exc_info=True)
                    results.append({"status": "error", "error": str(book_err), "title": getattr(msg.document, "file_name", "Desconocido")})

    # Construir reporte final del lote
    lines = [
        f"📚 <b>Lote de {total} libros procesado con éxito:</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    ]
    registered_count = 0
    for idx, r in enumerate(results, start=1):
        st = r.get("status")
        title = html.escape(r.get("title", "Sin título"))
        author = html.escape(r.get("author", "Desconocido"))
        genre = html.escape(r.get("genre", "General"))
        emoji = r.get("emoji", "📖")
        dest_link = r.get("dest_link")

        if st == "success":
            registered_count += 1
            link_html = f'<a href="{dest_link}">👉 Ver libro</a>' if dest_link else ""
            lines.append(f"<b>{idx}. {emoji} {title}</b>\n   ✍️ <i>{author}</i> | 🏷️ <b>{genre}</b> {link_html}\n")
        elif st == "duplicate":
            link_html = f'<a href="{dest_link}">👉 Ver existente</a>' if dest_link else ""
            lines.append(f"<b>{idx}. ℹ️ {title}</b> (<i>Ya registrado</i>) {link_html}\n")
        else:
            lines.append(f"<b>{idx}. ⚠️ {title}</b> — <i>Error al procesar</i>\n")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"✨ <i>{registered_count}/{total} libros archivados en sus estantes correspondientes.</i>")

    report_text = "\n".join(lines)
    if status_msg:
        try:
            await status_msg.edit_text(report_text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            await context.bot.send_message(chat_id=chat.id, message_thread_id=thread_id, text=report_text, parse_mode="HTML", disable_web_page_preview=True)
    else:
        await context.bot.send_message(chat_id=chat.id, message_thread_id=thread_id, text=report_text, parse_mode="HTML", disable_web_page_preview=True)


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Detecta cuando se envía uno o varios libros (PDF, EPUB, etc.).
    Soporta envíos individuales y lotes de múltiples archivos (álbumes / media groups).
    Utiliza Gemini AI para extraer título, autor y clasificar el género de forma 100% autónoma.
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not message.document:
        return

    doc = message.document
    filename = doc.file_name or "libro_desconocido"
    _, ext = clean_filename(filename)

    if f".{ext}" not in SUPPORTED_EXTENSIONS:
        logger.debug(f"Documento ignorado por extensión no soportada: {filename}")
        return

    import html

    # Caso A: El mensaje pertenece a un lote / álbum (media_group_id)
    mg_id = getattr(message, "media_group_id", None)
    if mg_id:
        if mg_id not in _media_group_batches:
            _media_group_batches[mg_id] = {
                "messages": [],
                "chat": chat,
                "thread_id": getattr(message, "message_thread_id", None),
                "timer": None
            }
        batch = _media_group_batches[mg_id]
        batch["messages"].append(message)

        if batch["timer"] and not batch["timer"].done():
            batch["timer"].cancel()

        async def _timer_cb():
            await asyncio.sleep(1.2)  # Espera a que lleguen todos los documentos del álbum
            await _process_media_group_batch(mg_id, context)

        batch["timer"] = asyncio.create_task(_timer_cb())
        return

    # Caso B: Libro individual (o mensaje sin media_group_id)
    async with get_chat_lock(chat.id):
        async with AsyncSessionLocal() as session:
            stmt = select(TelegramLink).where(TelegramLink.chat_id == chat.id)
            res = await session.execute(stmt)
            link = res.scalar_one_or_none()

            if not link:
                try:
                    status_info = await get_chat_and_bot_status(context.bot, chat.id)
                    chat_type_str = "group_forum" if status_info["forum_enabled"] else status_info["chat_type"]
                    link = TelegramLink(
                        user_id=1,
                        chat_id=chat.id,
                        chat_type=chat_type_str,
                        chat_title=status_info["chat_title"],
                        bot_is_admin=status_info["bot_is_admin"],
                        forum_enabled=status_info["forum_enabled"]
                    )
                    session.add(link)
                    await session.commit()
                    await session.refresh(link)
                except Exception as autolink_err:
                    logger.error(f"No se pudo auto-vincular chat {chat.id}: {autolink_err}")
                    return

            res_dict = await process_book_message(
                bot=context.bot,
                session=session,
                link=link,
                chat_id=chat.id,
                message=message,
                delete_original=link.bot_is_admin
            )

            st = res_dict.get("status")
            if st == "duplicate":
                title_safe = html.escape(res_dict["title"])
                author_safe = html.escape(res_dict["author"])
                genre_safe = html.escape(res_dict["genre"])
                fmt = res_dict["file_format"].upper()
                msg_link = res_dict.get("dest_link")
                link_html = f'<a href="{msg_link}">👉 Pulsa aquí para ir al libro en el tema</a>' if msg_link else ""
                await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=getattr(message, "message_thread_id", None),
                    text=f"ℹ️ <b>Este libro ya se encuentra en la biblioteca:</b>\n\n"
                         f"📖 <b>{title_safe}</b>\n"
                         f"✍️ <i>{author_safe}</i>\n"
                         f"🏷️ Tema: <b>{genre_safe}</b> (<code>.{fmt}</code>)\n\n"
                         f"{link_html}",
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                return

            if st == "success":
                title_safe = html.escape(res_dict["title"])
                author_safe = html.escape(res_dict["author"])
                genre_safe = html.escape(res_dict["genre"])
                emo = res_dict.get("emoji", "📖")
                dest_link = res_dict.get("dest_link")
                assigned_topic_id = res_dict.get("assigned_topic_id")
                current_thread_id = res_dict.get("current_thread_id")

                # Si el libro fue subido en un tema incorrecto o General y se reubicó, avisar en origen
                if assigned_topic_id and current_thread_id != assigned_topic_id:
                    try:
                        await context.bot.send_message(
                            chat_id=chat.id,
                            message_thread_id=current_thread_id,
                            text=f"🔄 <b>Libro organizado automáticamente:</b>\n\n"
                                 f"📖 <b>{title_safe}</b> (<i>{author_safe}</i>) pertenece a {emo} <b>{genre_safe}</b>.\n"
                                 f"Para mantener la biblioteca ordenada, ha sido archivado en su tema correspondiente.\n\n"
                                 f'👉 <a href="{dest_link}">Pulsa aquí para ver el libro en {genre_safe}</a>',
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                    except Exception as orig_err:
                        logger.debug(f"No se pudo enviar aviso de reubicación: {orig_err}")

                # Notificación en tema destino
                if assigned_topic_id:
                    try:
                        all_chat_books = (await session.execute(select(Book).where(Book.telegram_link_id == link.id))).scalars().all()
                        clean_c_id = str(chat.id).replace("-100", "").replace("-", "")
                        card_body = format_book_full_description(
                            book=res_dict,
                            chat_books=all_chat_books,
                            clean_chat_id=clean_c_id,
                            current_topic_name=genre_safe,
                            current_topic_emoji=emo
                        )
                        dest_text = (
                            f"📚 <b>Libro sincronizado y archivado:</b>\n\n"
                            f"{card_body}\n\n"
                            f"<i>(Clasificado y archivado automáticamente con IA)</i>"
                        )
                        await context.bot.send_message(
                            chat_id=chat.id,
                            message_thread_id=assigned_topic_id,
                            text=dest_text,
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        )
                    except Exception as notify_err:
                        logger.debug(f"No se pudo enviar confirmación: {notify_err}")



def build_catalog_page(chat_id: int, books: List[Book], page: int = 1, per_page: int = 5) -> tuple[str, InlineKeyboardMarkup]:
    """Genera el texto y la botonera de paginación del catálogo de libros con formato HTML seguro."""
    import html
    from app.services.ai_classifier import get_genre_emoji

    total_books = len(books)
    total_pages = max(1, (total_books + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_books = books[start_idx:end_idx]

    lines = [
        "📚 <b>Catálogo de Libros Disponibles</b>",
        f"<i>(Página {page} de {total_pages} — {total_books} libros registrados)</i>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    ]

    for i, b in enumerate(page_books, start=start_idx + 1):
        emo = get_genre_emoji(b.genre)
        pub_str = b.publication_year or "Desconocido"
        fmt = (b.file_format or "pdf").upper()

        title_safe = html.escape(b.title or "Sin título")
        author_safe = html.escape(b.author or "Desconocido")
        genre_safe = html.escape(b.genre or "General")

        book_chat = chat_id
        if getattr(b, "telegram_link", None) and getattr(b.telegram_link, "chat_id", None):
            book_chat = b.telegram_link.chat_id
        clean_chat_id = str(book_chat).replace("-100", "").replace("-", "")

        msg_link = f"https://t.me/c/{clean_chat_id}/{b.telegram_message_id}" if b.telegram_message_id and str(book_chat).startswith("-100") else None
        link_html = f'<a href="{msg_link}">👉 Ver libro</a>' if msg_link else "<i>(Sin enlace directo)</i>"

        lines.append(
            f"<b>{i}. 📖 {title_safe}</b>\n"
            f"   ✍️ Autor: <i>{author_safe}</i>\n"
            f"   🏷️ Tema: {emo} <b>{genre_safe}</b> (<code>.{fmt}</code>)\n"
            f"   📅 Publicación: <code>{pub_str}</code> | {link_html}\n"
        )

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Botones de paginación
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"catalog:page:{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="catalog:noop"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"catalog:page:{page + 1}"))

    keyboard = InlineKeyboardMarkup([nav_buttons]) if total_pages > 1 else InlineKeyboardMarkup([[]])
    return "\n".join(lines), keyboard


async def catalog_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /libros o /catalogo:
    Muestra la lista paginada de libros disponibles con título, autor, fecha, género y enlace directo.
    Funciona tanto en el tema General como dentro de cualquier tema o en chats privados.
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    thread_id = getattr(message, "message_thread_id", None)

    async with AsyncSessionLocal() as session:
        link = await _get_or_create_link(context.bot, session, chat.id)
        if not link:
            await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=thread_id,
                text="❌ Este grupo no está vinculado a Anaquel.",
                parse_mode="HTML"
            )
            return

        # Consultar libros (en privado consulta los del usuario, en grupo los del grupo)
        if chat.type == "private":
            stmt_books = (
                select(Book)
                .options(selectinload(Book.telegram_link))
                .where(Book.user_id == link.user_id)
                .order_by(Book.uploaded_at.desc())
            )
        else:
            stmt_books = (
                select(Book)
                .options(selectinload(Book.telegram_link))
                .where(Book.telegram_link_id == link.id)
                .order_by(Book.uploaded_at.desc())
            )
        b_res = await session.execute(stmt_books)
        books = b_res.scalars().all()

        if not books:
            empty_text = (
                "📚 <b>La biblioteca aún está vacía.</b>\n\n"
                "Sube libros en formato PDF o EPUB al chat o a cualquier tema para empezar a armar el catálogo."
            )
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=thread_id,
                    text=empty_text,
                    parse_mode="HTML"
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=empty_text,
                    parse_mode="HTML"
                )
            return

        text, keyboard = build_catalog_page(chat.id, books, page=1)
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=thread_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception:
            await context.bot.send_message(
                chat_id=chat.id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
                disable_web_page_preview=True
            )


async def catalog_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja los clics de paginación de /libros sin bloquearse."""
    query = update.callback_query
    if not query or not query.data:
        return

    try:
        await query.answer()
    except Exception as e:
        logger.debug(f"Error silencioso en query.answer(): {e}")

    data = query.data
    if data == "catalog:noop":
        return

    if data.startswith("catalog:page:"):
        page_num = int(data.split(":")[-1])
        chat = update.effective_chat
        if not chat:
            return

        async with AsyncSessionLocal() as session:
            link = await _get_or_create_link(context.bot, session, chat.id)
            if not link:
                return

            if chat.type == "private":
                stmt_books = (
                    select(Book)
                    .options(selectinload(Book.telegram_link))
                    .where(Book.user_id == link.user_id)
                    .order_by(Book.uploaded_at.desc())
                )
            else:
                stmt_books = (
                    select(Book)
                    .options(selectinload(Book.telegram_link))
                    .where(Book.telegram_link_id == link.id)
                    .order_by(Book.uploaded_at.desc())
                )
            b_res = await session.execute(stmt_books)
            books = b_res.scalars().all()

            text, keyboard = build_catalog_page(chat.id, books, page=page_num)
            try:
                await query.edit_message_text(
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            except Exception as edit_err:
                logger.error(f"Error editando mensaje de catálogo en página {page_num}: {edit_err}")


_search_query_cache: Dict[str, Tuple[str, float]] = {}  # token -> (query_text, timestamp)

def _normalize_search_string(text: str) -> str:
    import unicodedata
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text).encode("ASCII", "ignore").decode("utf-8")
    return nfkd.lower().strip()

def build_search_results_page(
    chat_id: int,
    query_text: str,
    token: str,
    books: List[Book],
    page: int = 1,
    per_page: int = 5
) -> tuple[str, InlineKeyboardMarkup]:
    """Genera el texto y los botones de paginación interactiva para resultados de búsqueda."""
    import html
    from app.services.ai_classifier import get_genre_emoji

    total_books = len(books)
    total_pages = max(1, (total_books + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_books = books[start_idx:end_idx]

    q_safe = html.escape(query_text)

    lines = [
        f"🔍 <b>Resultados para:</b> <i>\"{q_safe}\"</i>",
        f"<i>(Página {page} de {total_pages} — {total_books} libro(s) encontrado(s))</i>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    ]

    for i, b in enumerate(page_books, start=start_idx + 1):
        emo = get_genre_emoji(b.genre)
        pub_str = b.publication_year or "Desconocido"
        fmt = (b.file_format or "pdf").upper()

        title_safe = html.escape(b.title or "Sin título")
        author_safe = html.escape(b.author or "Desconocido")
        genre_safe = html.escape(b.genre or "General")

        book_chat = chat_id
        if getattr(b, "telegram_link", None) and getattr(b.telegram_link, "chat_id", None):
            book_chat = b.telegram_link.chat_id
        clean_chat_id = str(book_chat).replace("-100", "").replace("-", "")

        msg_link = f"https://t.me/c/{clean_chat_id}/{b.telegram_message_id}" if b.telegram_message_id and str(book_chat).startswith("-100") else None
        link_html = f'<a href="{msg_link}">👉 Ver libro</a>' if msg_link else "<i>(Sin enlace directo)</i>"

        lines.append(
            f"<b>{i}. 📖 {title_safe}</b>\n"
            f"   ✍️ Autor: <i>{author_safe}</i>\n"
            f"   🏷️ Tema: {emo} <b>{genre_safe}</b> (<code>.{fmt}</code>)\n"
            f"   📅 Publicación: <code>{pub_str}</code> | {link_html}\n"
        )

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"search:{token}:{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="search:noop"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"search:{token}:{page + 1}"))

    keyboard = InlineKeyboardMarkup([nav_buttons]) if total_pages > 1 else InlineKeyboardMarkup([[]])
    return "\n".join(lines), keyboard


async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /buscar o /search:
    Busca libros por título o autor (sin distinción de mayúsculas ni tildes).
    Muestra todos los libros del autor o todas las coincidencias de título.
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    thread_id = getattr(message, "message_thread_id", None)
    raw_query = " ".join(context.args).strip() if context.args else ""

    if not raw_query:
        help_search = (
            "🔍 <b>Búsqueda en la Biblioteca de Anaquel:</b>\n\n"
            "Escribe el nombre del libro o autor que deseas encontrar.\n\n"
            "<b>Ejemplos de uso:</b>\n"
            "• <code>/buscar Cecelia Ahern</code> — <i>Muestra todos sus libros</i>\n"
            "• <code>/buscar El Gran Gatsby</code> — <i>Busca por título</i>\n"
            "• <code>/buscar Mario Benedetti</code>\n"
            "• <code>/buscar Harry Potter</code>"
        )
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=thread_id,
                text=help_search,
                parse_mode="HTML"
            )
        except Exception:
            await context.bot.send_message(
                chat_id=chat.id,
                text=help_search,
                parse_mode="HTML"
            )
        return

    import time
    import hashlib

    # Limpiar entradas viejas de caché (> 2 horas)
    now = time.time()
    for k in list(_search_query_cache.keys()):
        if now - _search_query_cache[k][1] > 7200:
            _search_query_cache.pop(k, None)

    token = hashlib.md5(f"{chat.id}:{raw_query}".encode()).hexdigest()[:8]
    _search_query_cache[token] = (raw_query, now)

    async with AsyncSessionLocal() as session:
        link = await _get_or_create_link(context.bot, session, chat.id)
        if not link:
            await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=thread_id,
                text="❌ Este grupo no está vinculado a Anaquel.",
                parse_mode="HTML"
            )
            return

        # Consultar libros (en privado consulta los del usuario, en grupo los del grupo)
        if chat.type == "private":
            stmt_books = (
                select(Book)
                .options(selectinload(Book.telegram_link))
                .where(Book.user_id == link.user_id)
                .order_by(Book.title.asc())
            )
        else:
            stmt_books = (
                select(Book)
                .options(selectinload(Book.telegram_link))
                .where(Book.telegram_link_id == link.id)
                .order_by(Book.title.asc())
            )
        b_res = await session.execute(stmt_books)
        all_books = b_res.scalars().all()

        # Filtrar por tokens normalizados
        q_tokens = [_normalize_search_string(t) for t in raw_query.split() if t.strip()]
        matches = []
        for b in all_books:
            searchable = f"{_normalize_search_string(b.title)} {_normalize_search_string(b.author or '')} {_normalize_search_string(b.genre or '')}"
            if all(t in searchable for t in q_tokens):
                matches.append(b)

        if not matches:
            q_safe = html.escape(raw_query)
            no_results = (
                f"🔍 <b>No se encontraron libros para:</b> <i>\"{q_safe}\"</i>\n\n"
                "• Prueba escribiendo solo una palabra del título o el apellido del autor.\n"
                "• Usa <code>/libros</code> para explorar toda la biblioteca disponible."
            )
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=thread_id,
                    text=no_results,
                    parse_mode="HTML"
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=no_results,
                    parse_mode="HTML"
                )
            return

        text, keyboard = build_search_results_page(chat.id, raw_query, token, matches, page=1)
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=thread_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception:
            await context.bot.send_message(
                chat_id=chat.id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
                disable_web_page_preview=True
            )


async def search_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la paginación interactiva de resultados de búsqueda."""
    query = update.callback_query
    if not query or not query.data:
        return

    try:
        await query.answer()
    except Exception as e:
        logger.debug(f"Error silencioso en search query.answer(): {e}")

    data = query.data
    if data == "search:noop":
        return

    parts = data.split(":")
    if len(parts) == 3 and parts[0] == "search":
        token = parts[1]
        try:
            page_num = int(parts[2])
        except ValueError:
            return

        chat = update.effective_chat
        if not chat:
            return

        cached_entry = _search_query_cache.get(token)
        if not cached_entry:
            try:
                await query.edit_message_text("⚠️ <i>Esta búsqueda ha expirado. Realiza una nueva con /buscar.</i>", parse_mode="HTML")
            except Exception:
                pass
            return

        raw_query = cached_entry[0]

        async with AsyncSessionLocal() as session:
            link = await _get_or_create_link(context.bot, session, chat.id)
            if not link:
                return

            if chat.type == "private":
                stmt_books = (
                    select(Book)
                    .options(selectinload(Book.telegram_link))
                    .where(Book.user_id == link.user_id)
                    .order_by(Book.title.asc())
                )
            else:
                stmt_books = (
                    select(Book)
                    .options(selectinload(Book.telegram_link))
                    .where(Book.telegram_link_id == link.id)
                    .order_by(Book.title.asc())
                )
            b_res = await session.execute(stmt_books)
            all_books = b_res.scalars().all()

            q_tokens = [_normalize_search_string(t) for t in raw_query.split() if t.strip()]
            matches = [
                b for b in all_books
                if all(t in f"{_normalize_search_string(b.title)} {_normalize_search_string(b.author or '')} {_normalize_search_string(b.genre or '')}" for t in q_tokens)
            ]

            text, keyboard = build_search_results_page(chat.id, raw_query, token, matches, page=page_num)
            try:
                await query.edit_message_text(
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            except Exception as edit_err:
                logger.error(f"Error editando resultados de búsqueda en página {page_num}: {edit_err}")


_download_cache: Dict[str, Tuple[List[Dict[str, Any]], float]] = {}  # token -> (books_list, timestamp)

async def download_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /descargar o /pedir o /download:
    Busca libros en fuentes públicas y oficiales (Internet Archive, Project Gutenberg)
    y permite al usuario descargarlos y archivarlos directamente en la biblioteca.
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    thread_id = getattr(message, "message_thread_id", None)
    raw_query = " ".join(context.args).strip() if context.args else ""

    if not raw_query:
        help_dl = (
            "📥 <b>Búsqueda y Descarga de Libros:</b>\n\n"
            "Escribe el nombre del libro o autor que deseas descargar en EPUB o PDF.\n\n"
            "<b>Ejemplos de uso:</b>\n"
            "• <code>/descargar El Principito</code>\n"
            "• <code>/descargar Don Quijote</code>\n"
            "• <code>/descargar Cumbres Borrascosas</code>\n"
            "• <code>/descargar Edgar Allan Poe</code>"
        )
        try:
            await context.bot.send_message(chat_id=chat.id, message_thread_id=thread_id, text=help_dl, parse_mode="HTML")
        except Exception:
            await context.bot.send_message(chat_id=chat.id, text=help_dl, parse_mode="HTML")
        return

    # Mensaje temporal de búsqueda
    status_msg = None
    try:
        status_msg = await context.bot.send_message(
            chat_id=chat.id,
            message_thread_id=thread_id,
            text=f"🔍 <i>Buscando libros disponibles para descargar: \"{html.escape(raw_query)}\"...</i>",
            parse_mode="HTML"
        )
    except Exception:
        status_msg = await context.bot.send_message(
            chat_id=chat.id,
            text=f"🔍 <i>Buscando libros disponibles para descargar: \"{html.escape(raw_query)}\"...</i>",
            parse_mode="HTML"
        )

    from app.services.book_download_service import search_external_books
    import time
    import hashlib

    # Limpiar entradas de caché viejas (> 2 horas)
    now = time.time()
    for k in list(_download_cache.keys()):
        if now - _download_cache[k][1] > 7200:
            _download_cache.pop(k, None)

    try:
        results = await search_external_books(raw_query, max_results=5)
    except Exception as e:
        logger.error(f"Error buscando libros externos: {e}")
        await status_msg.edit_text(f"❌ Error al consultar los repositorios: {str(e)[:200]}", parse_mode="HTML")
        return

    if not results:
        no_res = (
            f"❌ <b>No se encontraron libros para:</b> <i>\"{html.escape(raw_query)}\"</i>\n\n"
            "• Intenta con el título exacto o el nombre del autor en español.\n"
            "• La búsqueda abarca Internet Archive, Project Gutenberg y Library Genesis."
        )
        await status_msg.edit_text(no_res, parse_mode="HTML")
        return

    token = hashlib.md5(f"{chat.id}:{raw_query}:{time.time()}".encode()).hexdigest()[:8]
    _download_cache[token] = (results, now)

    lines = [
        f"📥 <b>Libros disponibles para descargar:</b>",
        f"<i>Búsqueda: \"{html.escape(raw_query)}\"</i>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    ]

    buttons = []
    for idx, b in enumerate(results, start=1):
        fmt = b["format"].upper()
        size_str = b.get("size_str") or "Directo"
        src = b.get("source", "Web")
        yr_str = f" | 📅 {b['year']}" if b.get("year") else ""

        title_safe = html.escape(b["title"])
        author_safe = html.escape(b.get("author", "Desconocido"))

        lines.append(
            f"<b>{idx}. 📖 {title_safe}</b>\n"
            f"   ✍️ Autor: <i>{author_safe}</i>\n"
            f"   🏷️ Formato: <code>.{fmt}</code> ({size_str}) | 🏛️ {src}{yr_str}\n"
        )
        buttons.append([InlineKeyboardButton(f"📥 Descargar #{idx} (.{fmt})", callback_data=f"dl:{token}:{idx - 1}")])

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("👇 <i>Selecciona qué opción deseas descargar y archivar:</i>")

    keyboard = InlineKeyboardMarkup(buttons)
    await status_msg.edit_text("\n".join(lines), reply_markup=keyboard, parse_mode="HTML")


async def download_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la confirmación de descarga cuando el usuario pulsa un botón."""
    query = update.callback_query
    if not query or not query.data:
        return

    try:
        await query.answer("⏳ Descargando libro y preparando estante...")
    except Exception:
        pass

    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "dl":
        return

    token, idx_str = parts[1], parts[2]
    try:
        idx = int(idx_str)
    except ValueError:
        return

    cached_entry = _download_cache.get(token)
    if not cached_entry:
        await query.edit_message_text("⚠️ <i>Esta solicitud de descarga ha expirado. Usa /descargar nuevamente.</i>", parse_mode="HTML")
        return

    results = cached_entry[0]
    if idx < 0 or idx >= len(results):
        await query.edit_message_text("⚠️ Opción no válida.", parse_mode="HTML")
        return

    chosen_book = results[idx]
    title_safe = html.escape(chosen_book["title"])
    fmt = chosen_book["format"].upper()

    await query.edit_message_text(
        f"⏳ <b>Descargando:</b> <i>{title_safe}</i> (<code>.{fmt}</code>)...\n"
        f"<i>Por favor espera unos segundos mientras se descarga, analiza con IA y se ubica en su tema.</i>",
        parse_mode="HTML"
    )

    chat = update.effective_chat
    if not chat:
        return

    from app.services.book_download_service import download_book_bytes, ingest_downloaded_book
    from app.services.book_processor import get_chat_lock

    async with get_chat_lock(chat.id):
        # 1. Descargar bytes
        try:
            file_bytes, filename = await download_book_bytes(chosen_book["download_url"])
        except Exception as dl_err:
            logger.error(f"Error descargando libro desde {chosen_book['download_url']}: {dl_err}")
            await query.edit_message_text(
                f"❌ <b>Error al descargar el archivo:</b> {html.escape(str(dl_err)[:200])}",
                parse_mode="HTML"
            )
            return

        # 2. Ingestar en la biblioteca
        async with AsyncSessionLocal() as session:
            stmt = select(TelegramLink).where(TelegramLink.chat_id == chat.id)
            res = await session.execute(stmt)
            link = res.scalar_one_or_none()

            if not link:
                status_info = await get_chat_and_bot_status(context.bot, chat.id)
                chat_type_str = "group_forum" if status_info["forum_enabled"] else status_info["chat_type"]
                link = TelegramLink(
                    user_id=1,
                    chat_id=chat.id,
                    chat_type=chat_type_str,
                    chat_title=status_info["chat_title"],
                    bot_is_admin=status_info["bot_is_admin"],
                    forum_enabled=status_info["forum_enabled"]
                )
                session.add(link)
                await session.commit()
                await session.refresh(link)

            try:
                ingest_res = await ingest_downloaded_book(
                    bot=context.bot,
                    session=session,
                    link=link,
                    chat_id=chat.id,
                    file_bytes=file_bytes,
                    filename=filename,
                    original_meta=chosen_book
                )
            except Exception as ing_err:
                logger.error(f"Error ingestando libro descargado: {ing_err}", exc_info=True)
                await query.edit_message_text(
                    f"❌ <b>Error al archivar el libro:</b> {html.escape(str(ing_err)[:200])}",
                    parse_mode="HTML"
                )
                return

    st = ingest_res.get("status")
    b_title = html.escape(ingest_res.get("title", chosen_book["title"]))
    b_author = html.escape(ingest_res.get("author", chosen_book.get("author", "Desconocido")))
    b_genre = html.escape(ingest_res.get("genre", "General"))
    b_year = html.escape(ingest_res.get("publication_year", chosen_book.get("year") or "Desconocido"))
    b_emoji = ingest_res.get("emoji", "📖")
    dest_link = ingest_res.get("dest_link")
    link_html = f'<a href="{dest_link}">👉 Ir al libro en el tema {b_genre}</a>' if dest_link else ""

    if st == "duplicate":
        await query.edit_message_text(
            f"ℹ️ <b>Este libro ya se encontraba en la biblioteca:</b>\n\n"
            f"📖 <b>{b_title}</b>\n"
            f"✍️ <i>{b_author}</i>\n"
            f"🏷️ Tema: {b_emoji} <b>{b_genre}</b> (<code>.{fmt}</code>)\n\n"
            f"{link_html}",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    elif st == "success":
        clean_c_id = str(chat.id).replace("-100", "").replace("-", "")
        async with AsyncSessionLocal() as sess_cb:
            stmt_all = select(Book).where(Book.telegram_link_id == link.id)
            all_chat_books = (await sess_cb.execute(stmt_all)).scalars().all()

        card_body = format_book_full_description(
            book=ingest_res,
            chat_books=all_chat_books,
            clean_chat_id=clean_c_id,
            current_topic_name=b_genre,
            current_topic_emoji=b_emoji
        )
        await query.edit_message_text(
            f"✅ <b>¡Libro descargado y archivado exitosamente!</b>\n\n"
            f"{card_body}\n\n"
            f"{link_html}",
            parse_mode="HTML",
            disable_web_page_preview=True
        )



async def topics_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /temas:
    Lista todos los temas activos y cuántos libros tiene cada uno.
    Funciona tanto en el tema General como dentro de cualquier tema o en privado.
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    import html
    thread_id = getattr(message, "message_thread_id", None)
    from app.services.ai_classifier import get_genre_emoji

    async with AsyncSessionLocal() as session:
        link = await _get_or_create_link(context.bot, session, chat.id)
        if not link:
            await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=thread_id,
                text="❌ Este grupo no está vinculado a Anaquel.",
                parse_mode="HTML"
            )
            return

        stmt_topics = select(Topic).where(Topic.telegram_link_id == link.id).order_by(Topic.genre.asc())
        t_res = await session.execute(stmt_topics)
        topics = t_res.scalars().all()

        # Contar libros por tema
        if chat.type == "private":
            stmt_books = select(Book).where(Book.user_id == link.user_id)
        else:
            stmt_books = select(Book).where(Book.telegram_link_id == link.id)
        b_res = await session.execute(stmt_books)
        all_books = b_res.scalars().all()

        counts = {}
        for b in all_books:
            counts[b.genre] = counts.get(b.genre, 0) + 1

        if not topics and not all_books:
            empty_msg = (
                "ℹ️ <b>Aún no hay temas registrados en este grupo.</b>\n\n"
                "Sube libros para que Anaquel cree automáticamente cada estante por género."
            )
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=thread_id,
                    text=empty_msg,
                    parse_mode="HTML"
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=empty_msg,
                    parse_mode="HTML"
                )
            return

        clean_chat_id = str(chat.id).replace("-100", "").replace("-", "")

        header = (
            "🏷️ <b>Temas y Géneros Disponibles en Anaquel</b>\n"
            f"<i>(Total: {len(topics) if topics else len(counts)} estantes registrados)</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        footer = "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n💡 <i>Pulsa sobre cualquier tema para entrar directamente a él.</i>"

        topic_lines = []
        if topics:
            for t in topics:
                emo = get_genre_emoji(t.genre)
                qty = counts.get(t.genre, 0)
                genre_safe = html.escape(t.genre)
                if str(chat.id).startswith("-100"):
                    topic_link = f"https://t.me/c/{clean_chat_id}/{t.topic_id}"
                    topic_lines.append(f'• {emo} <a href="{topic_link}"><b>{genre_safe}</b></a> — <code>{qty} libro(s)</code>')
                else:
                    topic_lines.append(f'• {emo} <b>{genre_safe}</b> — <code>{qty} libro(s)</code>')
        else:
            for genre_name, qty in sorted(counts.items(), key=lambda x: x[0]):
                emo = get_genre_emoji(genre_name)
                genre_safe = html.escape(genre_name)
                topic_lines.append(f'• {emo} <b>{genre_safe}</b> — <code>{qty} libro(s)</code>')

        # Chunking para respetar el límite de 4096 caracteres de Telegram
        chunks = []
        cur_chunk = [header]
        cur_len = len(header) + len(footer)
        for t_line in topic_lines:
            if cur_len + len(t_line) + 1 > 3800:
                cur_chunk.append(footer)
                chunks.append("\n".join(cur_chunk))
                cur_chunk = [header, t_line]
                cur_len = len(header) + len(t_line) + len(footer)
            else:
                cur_chunk.append(t_line)
                cur_len += len(t_line) + 1
        if cur_chunk:
            cur_chunk.append(footer)
            chunks.append("\n".join(cur_chunk))

        for chunk_text in chunks:
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=thread_id,
                    text=chunk_text,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=chunk_text,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )


async def topic_index_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /indice:
    Debe ejecutarse DENTRO de un tema. Publica un mensaje índice formateado con todos
    los libros disponibles en este tema específico, con enlaces directos para fijar.
    Soporta temas grandes fragmentando mensajes sin exceder el límite de Telegram.
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    import html
    thread_id = getattr(message, "message_thread_id", None)
    if not thread_id:
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text="⚠️ Este comando debe ejecutarse <b>dentro</b> del tema que deseas indexar.",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    from app.services.ai_classifier import get_genre_emoji

    async with AsyncSessionLocal() as session:
        link = await _get_or_create_link(context.bot, session, chat.id)
        if not link:
            await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=thread_id,
                text="❌ Este grupo no está vinculado a Anaquel.",
                parse_mode="HTML"
            )
            return

        stmt_topic = select(Topic).where(
            Topic.telegram_link_id == link.id,
            Topic.topic_id == thread_id
        )
        t_res = await session.execute(stmt_topic)
        topic = t_res.scalar_one_or_none()

        genre_name = topic.genre if topic else "General"
        emo = get_genre_emoji(genre_name)

        stmt_books = (
            select(Book)
            .options(selectinload(Book.telegram_link))
            .where(Book.telegram_link_id == link.id, Book.genre == genre_name)
            .order_by(Book.title.asc())
        )
        b_res = await session.execute(stmt_books)
        books = b_res.scalars().all()

        clean_chat_id = str(chat.id).replace("-100", "").replace("-", "")

        header = (
            f"📌 <b>ÍNDICE DE LA COLECCIÓN: {emo} {html.escape(genre_name)}</b>\n"
            f"<i>(Total: {len(books)} libros disponibles)</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        footer = "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n💡 <i>Tip para Administradores: Fija este mensaje en el tema para que los lectores lo vean al entrar.</i>"

        if not books:
            empty_index = header + "<i>(Aún no hay libros archivados en este tema)</i>\n" + footer
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=thread_id,
                    text=empty_index,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=empty_index,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            return

        book_lines = []
        for i, b in enumerate(books, start=1):
            fmt = (b.file_format or "pdf").upper()
            book_chat = chat.id
            if getattr(b, "telegram_link", None) and getattr(b.telegram_link, "chat_id", None):
                book_chat = b.telegram_link.chat_id
            b_clean = str(book_chat).replace("-100", "").replace("-", "")
            msg_link = f"https://t.me/c/{b_clean}/{b.telegram_message_id}" if b.telegram_message_id and str(book_chat).startswith("-100") else None
            link_html = f'<a href="{msg_link}">👉 Ver libro</a>' if msg_link else ""
            title_safe = html.escape(b.title or "Sin título")
            author_safe = html.escape(b.author or "Desconocido")
            pub_yr = f" ({b.publication_year})" if b.publication_year and b.publication_year != "Desconocido" else ""
            book_lines.append(f"<b>{i}.</b> 📖 <b>{title_safe}</b>{pub_yr} — <i>{author_safe}</i> (<code>.{fmt}</code>) {link_html}")

        # Fragmentación segura en bloques de < 3800 caracteres
        chunks = []
        cur_chunk = [header]
        cur_len = len(header) + len(footer)
        part = 1
        for b_line in book_lines:
            if cur_len + len(b_line) + 1 > 3800:
                cur_chunk.append(footer)
                chunks.append("\n".join(cur_chunk))
                part += 1
                part_hdr = f"📌 <b>ÍNDICE DE LA COLECCIÓN (Parte {part}): {emo} {html.escape(genre_name)}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                cur_chunk = [part_hdr, b_line]
                cur_len = len(part_hdr) + len(b_line) + len(footer)
            else:
                cur_chunk.append(b_line)
                cur_len += len(b_line) + 1

        if cur_chunk:
            cur_chunk.append(footer)
            chunks.append("\n".join(cur_chunk))

        for text_chunk in chunks:
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=thread_id,
                    text=text_chunk,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=text_chunk,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )


async def register_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /registrar o /indexar:
    Permite catalogar libros antiguos o asignarles título/autor personalizado.
    Uso:
    • /registrar (Detección automática e inspección interna con IA)
    • /registrar Título - Autor (Para asignar nombre manual si el archivo tiene nombres raros)
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    if not message.reply_to_message or not message.reply_to_message.document:
        await message.reply_text(
            "⚠️ <b>Modo de Uso:</b>\n"
            "Responde al mensaje que contenga el libro (PDF o EPUB) escribiendo:\n"
            "• <code>/registrar</code> — <i>(Detección automática con IA)</i>\n"
            "• <code>/registrar &lt;Título&gt; - &lt;Autor&gt;</code> — <i>(Asignación manual si el nombre es raro)</i>",
            parse_mode="HTML"
        )
        return

    target_msg = message.reply_to_message
    doc = target_msg.document
    filename = doc.file_name or "libro_antiguo"
    _, ext = clean_filename(filename)

    if f".{ext}" not in SUPPORTED_EXTENSIONS:
        await message.reply_text(f"⚠️ Extensión <code>.{ext}</code> no soportada.", parse_mode="HTML")
        return

    # Si el usuario especificó /registrar Título - Autor, usarlo como caption/pista prioritaria
    custom_input = " ".join(context.args).strip() if context.args else None

    status_msg = await message.reply_text("⏳ <i>Procesando libro y analizando contenido con IA...</i>", parse_mode="HTML")

    try:
        async with get_chat_lock(chat.id):
            async with AsyncSessionLocal() as session:
                link = await _get_or_create_link(context.bot, session, chat.id)
                if not link:
                    await status_msg.edit_text("❌ Este grupo no está vinculado a Anaquel.", parse_mode="HTML")
                    return

                res_dict = await process_book_message(
                    bot=context.bot,
                    session=session,
                    link=link,
                    chat_id=chat.id,
                    message=target_msg,
                    delete_original=link.bot_is_admin,
                    caption_override=custom_input
                )

        st = res_dict.get("status")
        title_safe = html.escape(res_dict.get("title", filename))
        author_safe = html.escape(res_dict.get("author", "Desconocido"))
        genre_safe = html.escape(res_dict.get("genre", "General"))
        emo = res_dict.get("emoji", "📖")
        dest_link = res_dict.get("dest_link")
        link_html = f'<a href="{dest_link}">👉 Ir al libro en el tema</a>' if dest_link else ""

        if st == "duplicate":
            await status_msg.edit_text(
                f"ℹ️ <b>Este libro ya se encuentra en la biblioteca:</b>\n\n"
                f"📖 <b>{title_safe}</b>\n"
                f"✍️ <i>{author_safe}</i>\n"
                f"🏷️ Tema: <b>{genre_safe}</b>\n\n"
                f"{link_html}",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        elif st == "success":
            pub_str = res_dict.get("publication_year") or "Desconocido"
            await status_msg.edit_text(
                f"✅ <b>Libro registrado y archivado exitosamente:</b>\n\n"
                f"📖 <b>Título:</b> {title_safe}\n"
                f"✍️ <b>Autor:</b> {author_safe}\n"
                f"🏷️ <b>Tema:</b> {emo} <b>{genre_safe}</b>\n"
                f"📅 <b>Publicación:</b> <code>{pub_str}</code>\n\n"
                f"{link_html}",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        else:
            err = res_dict.get("error", "Error desconocido")
            await status_msg.edit_text(f"❌ <b>No se pudo registrar el libro:</b> {err}", parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error en register_reply_handler: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ <b>Error al procesar:</b> {str(e)[:200]}", parse_mode="HTML")


async def rename_book_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /renombrar o /editar:
    Permite corregir el título, autor o año de un libro.
    Uso: Responde al mensaje del libro con `/renombrar <Nuevo Título> - <Nuevo Autor>`
         o `/renombrar <Nuevo Título> - <Nuevo Autor> - <Año>`.
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    if not message.reply_to_message:
        await message.reply_text(
            "⚠️ <b>Modo de Uso:</b>\n"
            "Responde al mensaje del libro escribiendo:\n"
            "<code>/renombrar &lt;Nuevo Título&gt; - &lt;Nuevo Autor&gt;</code>\n"
            "<i>(Opcional con año):</i> <code>/renombrar &lt;Título&gt; - &lt;Autor&gt; - &lt;Año&gt;</code>\n\n"
            "<i>Ejemplo:</i>\n"
            "<code>/renombrar Cien Años de Soledad - Gabriel García Márquez - 1967</code>",
            parse_mode="HTML"
        )
        return

    target_msg = message.reply_to_message
    new_data = " ".join(context.args).strip() if context.args else ""
    if not new_data:
        await message.reply_text(
            "⚠️ Por favor indica el nuevo nombre del libro:\n"
            "<code>/renombrar Título - Autor</code>",
            parse_mode="HTML"
        )
        return

    parts = re.split(r"\s+[-–—]\s*", new_data)
    new_title = parts[0].strip().title()
    new_author = parts[1].strip().title() if len(parts) > 1 else "Desconocido"
    new_year = parts[2].strip() if len(parts) > 2 else None

    async with get_chat_lock(chat.id):
        async with AsyncSessionLocal() as session:
            link = await _get_or_create_link(context.bot, session, chat.id)
            if not link:
                await message.reply_text("❌ Este grupo no está vinculado a Anaquel.", parse_mode="HTML")
                return

            # Construir condiciones seguras sin IS NULL
            conditions = [Book.telegram_message_id == target_msg.message_id]
            if target_msg.document:
                fid = getattr(target_msg.document, "file_id", None)
                fuid = getattr(target_msg.document, "file_unique_id", None)
                if isinstance(fid, str):
                    conditions.append(Book.telegram_file_id == fid)
                if isinstance(fuid, str):
                    conditions.append(Book.file_unique_id == fuid)

            # Si el usuario respondió a un mensaje de aviso del bot con deep link
            raw_text = getattr(target_msg, "text", None) or getattr(target_msg, "caption", None)
            reply_text = raw_text if isinstance(raw_text, str) else ""
            link_match = re.search(r"t\.me/c/\d+/(\d+)", reply_text)
            if link_match:
                linked_msg_id = int(link_match.group(1))
                conditions.append(Book.telegram_message_id == linked_msg_id)

            stmt_book = select(Book).where(
                Book.telegram_link_id == link.id,
                or_(*conditions)
            )
            b_res = await session.execute(stmt_book)
            book = b_res.scalars().first()

            if not book and reply_text:
                # Intento de rescate por título extraído del aviso (📖 <b>Título</b> o 📖 Título)
                t_match = re.search(r"📖\s*(?:<b>)?([^<\n]+)", reply_text)
                if t_match:
                    card_title = t_match.group(1).strip()
                    stmt_fallback = select(Book).where(
                        Book.telegram_link_id == link.id,
                        Book.title == card_title
                    )
                    book = (await session.execute(stmt_fallback)).scalars().first()

            if not book:
                await message.reply_text(
                    "❌ No se encontró este libro en el registro de la biblioteca.\n"
                    "Puedes usar <code>/registrar " + html.escape(new_data) + "</code> respondiendo al archivo para indexarlo.",
                    parse_mode="HTML"
                )
                return

            book.title = new_title
            if new_author and new_author != "Desconocido":
                book.author = new_author
            if new_year:
                book.publication_year = new_year
            await session.commit()
            await session.refresh(book)

    title_safe = html.escape(book.title)
    author_safe = html.escape(book.author)
    emo = get_genre_emoji(book.genre)
    pub_info = f"📅 <b>Publicación:</b> <code>{book.publication_year or 'Desconocido'}</code>\n"
    await message.reply_text(
        f"✏️ <b>Libro actualizado con éxito:</b>\n\n"
        f"📖 <b>Título:</b> {title_safe}\n"
        f"✍️ <b>Autor:</b> {author_safe}\n"
        f"🏷️ <b>Tema:</b> {emo} <b>{book.genre}</b>\n"
        f"{pub_info}\n"
        f"<i>El catálogo y la aplicación Anaquel se han actualizado con la información correcta.</i>",
        parse_mode="HTML"
    )


async def sync_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /sincronizar o /limpiar:
    Escanea la biblioteca, depura automáticamente cualquier libro o tema que haya sido
    eliminado manualmente de Telegram y actualiza el catálogo y los estantes.
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    thread_id = getattr(message, "message_thread_id", None)
    status_msg = None
    try:
        status_msg = await context.bot.send_message(
            chat_id=chat.id,
            message_thread_id=thread_id,
            text="🔄 <i>Verificando y sincronizando estantes de Anaquel con Telegram...</i>",
            parse_mode="HTML"
        )
    except Exception:
        pass

    from app.services.book_sync_service import sync_all_library_for_chat

    async with AsyncSessionLocal() as session:
        link = await _get_or_create_link(context.bot, session, chat.id)
        if not link:
            err_text = "❌ Este grupo aún no está vinculado a Anaquel."
            if status_msg:
                await status_msg.edit_text(err_text, parse_mode="HTML")
            else:
                await context.bot.send_message(chat_id=chat.id, message_thread_id=thread_id, text=err_text, parse_mode="HTML")
            return

        sync_result = await sync_all_library_for_chat(context.bot, session, link.id, chat.id)

    purged = sync_result.get("purged_books", 0)
    duplicates = sync_result.get("duplicates_removed", 0)
    active = sync_result.get("active_books", 0)
    topics = sync_result.get("active_topics", 0)

    clean_text = (
        "🧹 <b>Sincronización y Mantenimiento Completados</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <b>Libros extraviados detectados:</b> <code>{purged}</code>\n"
        f"🗑️ <b>Copias duplicadas eliminadas:</b> <code>{duplicates}</code>\n"
        f"📚 <b>Libros activos en la biblioteca:</b> <code>{active}</code>\n"
        f"🏷️ <b>Temas organizados:</b> <code>{topics}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✨ <i>Los estantes y el catálogo coinciden exactamente con los libros existentes en el grupo.</i>"
    )

    if status_msg:
        try:
            await status_msg.edit_text(clean_text, parse_mode="HTML")
        except Exception:
            await context.bot.send_message(chat_id=chat.id, message_thread_id=thread_id, text=clean_text, parse_mode="HTML")
    else:
        await context.bot.send_message(chat_id=chat.id, message_thread_id=thread_id, text=clean_text, parse_mode="HTML")


async def deduplicate_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /deduplicar:
    Escanea la biblioteca, detecta libros duplicados por título y formato,
    elimina automáticamente los mensajes duplicados de Telegram y depura la base de datos.
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    thread_id = getattr(message, "message_thread_id", None)
    status_msg = None
    try:
        status_msg = await context.bot.send_message(
            chat_id=chat.id,
            message_thread_id=thread_id,
            text="🔍 <i>Escaneando la biblioteca en busca de libros duplicados...</i>",
            parse_mode="HTML"
        )
    except Exception:
        pass

    from app.services.book_sync_service import deduplicate_library_for_chat

    async with AsyncSessionLocal() as session:
        link = await _get_or_create_link(context.bot, session, chat.id)
        if not link:
            err_text = "❌ Este grupo no está vinculado a Anaquel."
            if status_msg:
                await status_msg.edit_text(err_text, parse_mode="HTML")
            else:
                await context.bot.send_message(chat_id=chat.id, message_thread_id=thread_id, text=err_text, parse_mode="HTML")
            return

        res = await deduplicate_library_for_chat(context.bot, session, link.id, chat.id)

    removed = res.get("duplicates_removed", 0)
    if removed > 0:
        details_text = ""
        for item in res.get("details", [])[:5]:
            details_text += f"• 📖 <b>{html.escape(item['title'])}</b> (<code>.{item['format'].upper()}</code>)\n"
        if removed > 5:
            details_text += f"<i>...y {removed - 5} libros más.</i>\n"

        result_text = (
            "🧹 <b>Deduplicación Automática Completada</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🗑️ <b>Libros duplicados eliminados:</b> <code>{removed}</code>\n\n"
            f"{details_text}"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "✨ <i>Se conservó la versión canónica de cada obra en su estante correspondiente y se eliminaron los mensajes repetidos en Telegram.</i>"
        )
    else:
        result_text = (
            "✨ <b>Biblioteca Limpia</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "No se encontraron libros duplicados en este grupo. Todas las obras registradas son únicas."
        )

    if status_msg:
        try:
            await status_msg.edit_text(result_text, parse_mode="HTML")
        except Exception:
            await context.bot.send_message(chat_id=chat.id, message_thread_id=thread_id, text=result_text, parse_mode="HTML")
    else:
        await context.bot.send_message(chat_id=chat.id, message_thread_id=thread_id, text=result_text, parse_mode="HTML")


async def lost_book_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Gestiona los botones interactivos de alerta de libros extraviados (rec:get:<id> y rec:del:<id>):
    - 'rec:get:<id>': Busca el libro en repositorios externos, lo descarga, lo publica en su tema y restaura el registro.
    - 'rec:del:<id>': Descarta el libro y depura el registro de la base de datos.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "rec":
        return

    action, book_id_str = parts[1], parts[2]
    try:
        book_id = int(book_id_str)
    except ValueError:
        return

    chat = update.effective_chat
    if not chat:
        return

    if action == "del":
        async with AsyncSessionLocal() as session:
            b = (await session.execute(select(Book).where(Book.id == book_id))).scalar_one_or_none()
            if b:
                title = b.title
                await session.delete(b)
                await session.commit()
                try:
                    await query.answer("🗑️ Libro descartado y depurado de la biblioteca.")
                except Exception:
                    pass
                await query.edit_message_text(
                    f"🗑️ <i>El libro <b>{html.escape(title)}</b> ha sido descartado y depurado de la biblioteca.</i>",
                    parse_mode="HTML"
                )
            else:
                try:
                    await query.answer("El registro ya había sido depurado.")
                except Exception:
                    pass
                await query.edit_message_text("🗑️ <i>Registro ya depurado.</i>", parse_mode="HTML")
        return

    if action == "get":
        try:
            await query.answer("⏳ Buscando copia de reemplazo...")
        except Exception:
            pass

        async with AsyncSessionLocal() as session:
            b = (await session.execute(select(Book).where(Book.id == book_id))).scalar_one_or_none()
            if not b:
                await query.edit_message_text("⚠️ <i>Este libro ya no figura en el registro de pendientes.</i>", parse_mode="HTML")
                return

            title = b.title
            author = b.author
            genre = b.genre

            await query.edit_message_text(
                f"⏳ <b>Buscando copia de reemplazo para:</b>\n"
                f"📖 <b>{html.escape(title)}</b> — <i>{html.escape(author or 'Desconocido')}</i>\n\n"
                f"<i>Consultando repositorios externos...</i>",
                parse_mode="HTML"
            )

            from app.services.book_download_service import (
                search_books_online,
                download_book_bytes,
                ingest_downloaded_book
            )

            query_str = f"{title} {author}" if author and author != "Desconocido" else title
            results = await search_books_online(query_str, limit=3)
            if not results and author and author != "Desconocido":
                results = await search_books_online(title, limit=3)

            if not results:
                await query.edit_message_text(
                    f"⚠️ <b>No se encontró copia automática disponible</b> para:\n"
                    f"📖 <b>{html.escape(title)}</b>\n\n"
                    f"<i>Puedes subir el archivo manualmente (PDF o EPUB) en este tema para restaurarlo.</i>",
                    parse_mode="HTML"
                )
                return

            best = results[0]
            await query.edit_message_text(
                f"📥 <b>Descargando reemplazo encontrado:</b>\n"
                f"📖 <i>{html.escape(best.get('title', title))}</i> (<code>.{best.get('format', 'epub').upper()}</code>)...\n\n"
                f"<i>Subiendo al estante temático de Telegram...</i>",
                parse_mode="HTML"
            )

            try:
                file_bytes, filename = await download_book_bytes(best["download_url"])
                link = (await session.execute(select(TelegramLink).where(TelegramLink.chat_id == chat.id))).scalar_one_or_none()
                if not link:
                    link = (await session.execute(select(TelegramLink).where(TelegramLink.id == b.telegram_link_id))).scalar_one_or_none()

                ingest_res = await ingest_downloaded_book(
                    bot=context.bot,
                    session=session,
                    link=link,
                    chat_id=chat.id,
                    file_bytes=file_bytes,
                    filename=filename,
                    original_meta=best
                )

                # Eliminar el registro antiguo huérfano para evitar duplicidad
                await session.delete(b)
                await session.commit()

                dest_link = ingest_res.get("dest_link")
                link_html = f'\n👉 <a href="{dest_link}">Pulsa aquí para ver el libro restaurado</a>' if dest_link else ""
                await query.edit_message_text(
                    f"✅ <b>¡Libro recuperado con éxito!</b>\n\n"
                    f"📖 <b>{html.escape(ingest_res.get('title', title))}</b>\n"
                    f"✍️ <i>{html.escape(ingest_res.get('author', author or 'Desconocido'))}</i>\n"
                    f"🏷️ Estante: <b>{html.escape(ingest_res.get('genre', genre or 'General'))}</b>"
                    f"{link_html}",
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            except Exception as dl_err:
                logger.error(f"Error restaurando libro extraviado {book_id}: {dl_err}")
                await query.edit_message_text(
                    f"❌ <b>Error al recuperar el archivo:</b> {html.escape(str(dl_err)[:200])}",
                    parse_mode="HTML"
                )


async def info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /info o /detalle o /saga:
    Muestra la ficha y descripción completa del libro:
    - Título, autor, género y año de publicación
    - Si pertenece a una saga o trilogía, su orden y total de entregas
    - Si tiene continuación o es autoconclusivo
    - Libro anterior y libro siguiente, indicando si están disponibles en algún tema de la biblioteca o no
    - Si este libro está en algún tema de la biblioteca (Tema actual)
    Uso:
      • Respondiendo a cualquier libro con /info
      • /info <nombre del libro o autor>
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    thread_id = getattr(message, "message_thread_id", None)
    clean_chat_id = str(chat.id).replace("-100", "").replace("-", "")

    async with AsyncSessionLocal() as session:
        link = await _get_or_create_link(context.bot, session, chat.id)
        if not link:
            await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=thread_id,
                text="❌ Este grupo no está vinculado a Anaquel.",
                parse_mode="HTML"
            )
            return

        if chat.type == "private":
            stmt_books = (
                select(Book)
                .options(selectinload(Book.telegram_link))
                .where(Book.user_id == link.user_id)
            )
        else:
            stmt_books = (
                select(Book)
                .options(selectinload(Book.telegram_link))
                .where(Book.telegram_link_id == link.id)
            )
        all_books = (await session.execute(stmt_books)).scalars().all()

        target_book = None

        # Caso 1: Se respondió a un mensaje (documento o ficha del bot)
        if message.reply_to_message:
            r_msg = message.reply_to_message
            r_doc = getattr(r_msg, "document", None)
            target_book = next((b for b in all_books if b.telegram_message_id == r_msg.message_id), None)
            if not target_book and r_doc:
                fid = getattr(r_doc, "file_id", None)
                fuid = getattr(r_doc, "file_unique_id", None)
                target_book = next((b for b in all_books if (isinstance(fuid, str) and b.file_unique_id == fuid) or (isinstance(fid, str) and b.telegram_file_id == fid)), None)

            if not target_book:
                raw_text = getattr(r_msg, "text", None) or getattr(r_msg, "caption", None)
                reply_text = raw_text if isinstance(raw_text, str) else ""
                link_match = re.search(r"t\.me/c/\d+/(\d+)", reply_text)
                if link_match:
                    linked_id = int(link_match.group(1))
                    target_book = next((b for b in all_books if b.telegram_message_id == linked_id), None)
                if not target_book and reply_text:
                    t_match = re.search(r"📖\s*(?:<b>)?([^<\n]+)", reply_text)
                    if t_match:
                        card_title = _normalize_search_string(t_match.group(1))
                        target_book = next((b for b in all_books if _normalize_search_string(b.title) == card_title), None)

        # Caso 2: Se especificó un término de búsqueda en /info <título o autor>
        if not target_book:
            query_text = " ".join(context.args).strip() if context.args else ""
            if not query_text:
                help_text = (
                    "ℹ️ <b>Información Detallada de Libros y Sagas:</b>\n\n"
                    "Consulta si un libro pertenece a una saga o trilogía, si tiene continuación, "
                    "cuáles libros le siguen o están antes, y si están en algún tema de la biblioteca.\n\n"
                    "<b>Formas de uso:</b>\n"
                    "• <code>/info &lt;título del libro&gt;</code>\n"
                    "• Responde a cualquier libro o ficha con <code>/info</code>\n\n"
                    "<b>Ejemplos:</b>\n"
                    "• <code>/info Bad Ash</code>\n"
                    "• <code>/info Harry Potter</code>\n"
                    "• <code>/info Los Juegos del Hambre</code>\n"
                    "• <code>/info Cien años de soledad</code>"
                )
                try:
                    await context.bot.send_message(
                        chat_id=chat.id,
                        message_thread_id=thread_id,
                        text=help_text,
                        parse_mode="HTML"
                    )
                except Exception:
                    await context.bot.send_message(chat_id=chat.id, text=help_text, parse_mode="HTML")
                return

            q_tokens = [_normalize_search_string(t) for t in query_text.split() if t.strip()]
            matches = [
                b for b in all_books
                if all(t in f"{_normalize_search_string(b.title)} {_normalize_search_string(b.author or '')}" for t in q_tokens)
            ]
            if not matches:
                matches = [
                    b for b in all_books
                    if any(t in _normalize_search_string(b.title) for t in q_tokens)
                ]

            if not matches:
                await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=thread_id,
                    text=f"❌ No se encontró ningún libro con el término <i>\"{html.escape(query_text)}\"</i> en la biblioteca.",
                    parse_mode="HTML"
                )
                return
            target_book = matches[0]

        # Enriquecer información de saga si es necesario
        await enrich_book_series_if_needed(target_book, session)

        book_chat = chat.id
        if getattr(target_book, "telegram_link", None) and getattr(target_book.telegram_link, "chat_id", None):
            book_chat = target_book.telegram_link.chat_id
        clean_c_id = str(book_chat).replace("-100", "").replace("-", "")

        # Armar la descripción completa
        desc_text = format_book_full_description(
            book=target_book,
            chat_books=all_books,
            clean_chat_id=clean_c_id,
            current_topic_name=target_book.genre
        )

        if target_book.telegram_message_id and str(book_chat).startswith("-100"):
            book_url = f"https://t.me/c/{clean_c_id}/{target_book.telegram_message_id}"
            desc_text += f'\n\n👉 <a href="{book_url}">Pulsa aquí para ver el libro en su tema</a>'

        from app.services.buddy_read_service import find_co_readers_for_book
        co_readers = await find_co_readers_for_book(session, target_book.id)
        if co_readers:
            desc_text += f"\n\n👥 <b>Lectores actuales en el club ({len(co_readers)}):</b>\n"
            for cr in co_readers[:4]:
                desc_text += f"• <b>{html.escape(cr['name'])}</b>: {cr['progress_bar']}\n"
            desc_text += "👉 <i>Toca el botón abajo para sumarte a la lectura conjunta.</i>"

        info_buttons = [
            [
                InlineKeyboardButton("🤝 Leer en conjunto", callback_data=f"br:start:{target_book.id}"),
                InlineKeyboardButton("⭐ Favorito", callback_data=f"rs:fav:{target_book.id}")
            ]
        ]
        info_kb = InlineKeyboardMarkup(info_buttons)

        try:
            await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=thread_id,
                text=desc_text,
                reply_markup=info_kb,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception:
            await context.bot.send_message(
                chat_id=chat.id,
                text=desc_text,
                reply_markup=info_kb,
                parse_mode="HTML",
                disable_web_page_preview=True
            )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra la guía completa de comandos disponibles."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    thread_id = getattr(message, "message_thread_id", None)
    help_text = (
        "🤖 <b>Comandos Disponibles en Anaquel:</b>\n\n"
        "📚 <b>Biblioteca & Catálogo:</b>\n"
        "• <code>/info &lt;libro o autor&gt;</code> — Ficha detallada: saga/trilogía, continuación, libros anteriores/siguientes y temas.\n"
        "• <code>/descargar &lt;libro o autor&gt;</code> — Busca y descarga libros externos (EPUB/PDF) a la biblioteca.\n"
        "• <code>/buscar &lt;nombre o autor&gt;</code> — Encuentra libros en el catálogo existente.\n"
        "• <code>/libros</code> o <code>/catalogo</code> — Catálogo paginado con título, autor, publicación y tema.\n"
        "• <code>/temas</code> — Ver todos los géneros registrados con conteo de libros.\n"
        "• <code>/indice</code> — <i>(Dentro de un tema)</i> Genera la lista de libros de ese tema para fijar.\n\n"
        "⚙️ <b>Administración & Organización:</b>\n"
        "• <code>/deduplicar</code> — Escanea y elimina libros duplicados automáticamente en Telegram y catálogo.\n"
        "• <code>/sincronizar</code> o <code>/limpiar</code> — Depura libros eliminados, audita extraviados y actualiza estantes.\n"
        "• <code>/registrar</code> — Responde a un mensaje antiguo con PDF o EPUB para indexarlo (o <code>/registrar Título - Autor</code>).\n"
        "• <code>/renombrar &lt;Título&gt; - &lt;Autor&gt;</code> — Corrige el título o autor de un libro respondiendo a su mensaje.\n"
        "• <code>/settopic &lt;Género&gt;</code> — <i>(Dentro de un tema)</i> Asigna ese tema manualmente a un género.\n"
        "• <code>/start</code> — Ver estado del bot o vincular el grupo a la app móvil Anaquel.\n"
        "• <code>/help</code> — Ver este menú de ayuda.\n\n"
        "✨ <b>Modo Cero Fricción:</b> No necesitas comandos para libros nuevos: ¡solo envía cualquier PDF o EPUB al chat y Anaquel se encarga de todo!"
    )
    try:
        await context.bot.send_message(
            chat_id=chat.id,
            message_thread_id=thread_id,
            text=help_text,
            parse_mode="HTML"
        )
    except Exception:
        await context.bot.send_message(
            chat_id=chat.id,
            text=help_text,
            parse_mode="HTML"
        )


async def chat_member_update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Se dispara automáticamente cuando el bot es añadido a un grupo o promovido."""
    result = update.my_chat_member
    if not result:
        return

    new_member = result.new_chat_member
    if new_member and new_member.user.id == context.bot.id and new_member.status in ["member", "administrator"]:
        chat = update.effective_chat
        if not chat:
            return

        async with AsyncSessionLocal() as session:
            stmt = select(TelegramLink).where(TelegramLink.chat_id == chat.id)
            res = await session.execute(stmt)
            link = res.scalar_one_or_none()

            status_info = await get_chat_and_bot_status(context.bot, chat.id)
            chat_type_str = "group_forum" if status_info["forum_enabled"] else status_info["chat_type"]

            if not link:
                link = TelegramLink(
                    user_id=1,
                    chat_id=chat.id,
                    chat_type=chat_type_str,
                    chat_title=status_info["chat_title"],
                    bot_is_admin=status_info["bot_is_admin"],
                    forum_enabled=status_info["forum_enabled"]
                )
                session.add(link)
            else:
                link.chat_title = status_info["chat_title"]
                link.bot_is_admin = status_info["bot_is_admin"]
                link.forum_enabled = status_info["forum_enabled"]

            await session.commit()

            welcome_text = (
                "👋 <b>¡Hola a todos! Soy Griffin, el bibliotecario inteligente de LibroSync / Anaquel.</b>\n\n"
                "📚 <b>Estoy listo para organizar, enriquecer y gestionar la biblioteca de este grupo de forma completamente autónoma:</b>\n\n"
                "✨ <b>Modo Cero Fricción (Automático):</b>\n"
                "• <b>Sube cualquier libro:</b> Admite <b>PDF, EPUB, MOBI, CBR y CBZ</b> (individual o en álbumes/lotes).\n"
                "• <b>Análisis con IA:</b> Clasifico automáticamente título exacto, autor, año y género literario.\n"
                "• <b>Organización en Temas:</b> Creo y reubico cada libro en su tema/estante correspondiente con su emoji identificador.\n"
                "• <b>Detección de Sagas:</b> Identifico automáticamente sagas, trilogías, orden de entrega y continuaciones.\n"
                "• <b>Deduplicación Inteligente:</b> Elimino automáticamente copias duplicadas, conservando siempre la versión canónica.\n"
                "• <b>Centinela Anti-Pérdidas:</b> Si una cuenta se elimina o se borra un archivo, emito una alerta con botón de <b>Auto-Recuperación en 1-clic</b>.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "📖 <b>Exploración y Biblioteca:</b>\n"
                "• <code>/libros</code> o <code>/catalogo</code> — Ver catálogo interactivo paginado con enlaces directos.\n"
                "• <code>/buscar &lt;título o autor&gt;</code> — Búsqueda rápida e inteligente en el fondo bibliográfico.\n"
                "• <code>/temas</code> — Resumen de todos los géneros literarios y libros disponibles por estante.\n"
                "• <code>/info &lt;libro&gt;</code> — Ficha detallada de la obra, saga, co-lectores actuales y acciones rápidas.\n"
                "• <code>/descargar &lt;libro o autor&gt;</code> — Buscar y descargar libros externos a la biblioteca.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "👥 <b>Club de Lectura y Comunidad:</b>\n"
                "• <code>/leerjuntos &lt;libro&gt;</code> (o <code>/conjunta</code>) — Iniciar o unirse a una lectura conjunta con tarjeta interactiva y barras de avance en vivo.\n"
                "• <code>/mislibros</code> — Ver tus estantes personales: <i>Leyendo</i> (📖), <i>Favoritos</i> (⭐), <i>Terminados</i> (🏆) y <i>Por Leer</i> (📌).\n"
                "• <code>/progreso &lt;%&gt;</code> — Actualizar tu avance de lectura al instante (sincronizado con la app móvil).\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "⚙️ <b>Administración y Mantenimiento:</b>\n"
                "• <code>/deduplicar</code> — Escanear y eliminar automáticamente libros duplicados del grupo.\n"
                "• <code>/sincronizar</code> o <code>/limpiar</code> — Depurar libros eliminados, auditar extraviados y refrescar estantes.\n"
                "• <code>/indice</code> — <i>(Dentro de un tema)</i> Genera el índice de libros del tema para fijar.\n"
                "• <code>/registrar</code> — Responder a un archivo antiguo para indexarlo (o <code>/registrar Título - Autor</code>).\n"
                "• <code>/renombrar &lt;Título&gt; - &lt;Autor&gt;</code> — Corregir título o autor respondiendo al libro.\n"
                "• <code>/settopic &lt;Género&gt;</code> — <i>(Dentro de un tema)</i> Asignar manualmente el tema a un género.\n"
                "• <code>/help</code> — Ver la guía de ayuda y comandos en cualquier momento.\n\n"
                "💡 <i>Tip: Para que pueda crear temas automáticamente y organizar los libros, asegúrate de otorgarme permisos de Administrador con 'Administrar temas'.</i>"
            )
            try:
                await context.bot.send_message(chat_id=chat.id, text=welcome_text, parse_mode="HTML", disable_web_page_preview=True)
            except Exception as e:
                logger.debug(f"No se pudo enviar mensaje de bienvenida: {e}")


async def buddy_read_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /leerjuntos [título o autor] o /conjunta:
    Inicia o se une a una lectura conjunta de un libro en el grupo.
    Mínimo 2 personas, sin límite de lectores.
    Soporta:
      • Responder a un libro o anuncio con /leerjuntos
      • /leerjuntos <nombre del libro>
    """
    message = update.effective_message
    chat = update.effective_chat
    user_tg = update.effective_user
    if not message or not chat or not user_tg:
        return

    thread_id = getattr(message, "message_thread_id", None)

    async with AsyncSessionLocal() as session:
        link = await _get_or_create_link(context.bot, session, chat.id)
        if not link:
            await message.reply_text("❌ Este chat no está vinculado a Anaquel.", parse_mode="HTML")
            return

        if chat.type == "private":
            stmt_books = select(Book).options(selectinload(Book.telegram_link)).where(Book.user_id == link.user_id)
        else:
            stmt_books = select(Book).options(selectinload(Book.telegram_link)).where(Book.telegram_link_id == link.id)
        all_books = (await session.execute(stmt_books)).scalars().all()

        target_book = None
        if message.reply_to_message:
            r_msg = message.reply_to_message
            target_book = next((b for b in all_books if b.telegram_message_id == r_msg.message_id), None)
            if not target_book and getattr(r_msg, "document", None):
                doc = r_msg.document
                target_book = next((b for b in all_books if (b.file_unique_id and b.file_unique_id == doc.file_unique_id) or (b.telegram_file_id and b.telegram_file_id == doc.file_id)), None)
            if not target_book:
                reply_txt = getattr(r_msg, "text", None) or getattr(r_msg, "caption", None) or ""
                m_link = re.search(r"t\.me/c/\d+/(\d+)", reply_txt)
                if m_link:
                    linked_id = int(m_link.group(1))
                    target_book = next((b for b in all_books if b.telegram_message_id == linked_id), None)
                if not target_book and reply_txt:
                    t_match = re.search(r"📖\s*(?:<b>)?([^<\n]+)", reply_txt)
                    if t_match:
                        c_title = _normalize_search_string(t_match.group(1))
                        target_book = next((b for b in all_books if _normalize_search_string(b.title) == c_title), None)

        if not target_book:
            query_str = " ".join(context.args).strip() if context.args else ""
            if not query_str:
                help_br = (
                    "📖 <b>Lecturas Conjuntas en Anaquel:</b>\n\n"
                    "Lee un libro junto a otros miembros del club y compartan su avance en tiempo real.\n\n"
                    "<b>Formas de uso:</b>\n"
                    "• Responde a cualquier libro con <code>/leerjuntos</code>\n"
                    "• <code>/leerjuntos &lt;nombre del libro&gt;</code>\n\n"
                    "<b>Ejemplo:</b>\n"
                    "• <code>/leerjuntos El Gran Gatsby</code>"
                )
                await message.reply_text(help_br, parse_mode="HTML")
                return

            q_tokens = [_normalize_search_string(t) for t in query_str.split() if t.strip()]
            matches = [b for b in all_books if all(t in f"{_normalize_search_string(b.title)} {_normalize_search_string(b.author or '')}" for t in q_tokens)]
            if not matches:
                matches = [b for b in all_books if any(t in _normalize_search_string(b.title) for t in q_tokens)]

            if not matches:
                await message.reply_text(f"❌ No se encontró el libro <i>\"{html.escape(query_str)}\"</i> en la biblioteca.", parse_mode="HTML")
                return
            target_book = matches[0]

        from app.services.buddy_read_service import (
            get_or_create_user_from_telegram,
            find_active_buddy_reads_for_book,
            create_buddy_read,
            format_buddy_read_card
        )

        user_db = await get_or_create_user_from_telegram(session, user_tg)

        active_brs = await find_active_buddy_reads_for_book(session, target_book.id, telegram_link_id=link.id)
        if active_brs:
            buddy_read = active_brs[0]
        else:
            buddy_read = await create_buddy_read(
                session=session,
                book_id=target_book.id,
                creator_user=user_db,
                telegram_link_id=link.id,
                thread_id=thread_id,
                tg_user=user_tg
            )

        card_text, card_kb = format_buddy_read_card(buddy_read, target_book, buddy_read.members, chat.id)

        try:
            sent_msg = await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=thread_id,
                text=card_text,
                reply_markup=card_kb,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            buddy_read.telegram_message_id = sent_msg.message_id
            await session.commit()
        except Exception:
            sent_msg = await context.bot.send_message(
                chat_id=chat.id,
                text=card_text,
                reply_markup=card_kb,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            buddy_read.telegram_message_id = sent_msg.message_id
            await session.commit()


async def my_books_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /mislibros o /perfil:
    Muestra los estantes personales del usuario de Telegram:
    - Leyendo actualmente con barra de progreso
    - Libros favoritos
    - Terminados
    - Por leer / Lista de deseos
    """
    message = update.effective_message
    chat = update.effective_chat
    user_tg = update.effective_user
    if not message or not chat or not user_tg:
        return

    thread_id = getattr(message, "message_thread_id", None)

    from app.services.buddy_read_service import (
        get_or_create_user_from_telegram,
        get_user_reading_shelves,
        format_progress_bar
    )

    async with AsyncSessionLocal() as session:
        user_db = await get_or_create_user_from_telegram(session, user_tg)
        shelves = await get_user_reading_shelves(session, user_db.id)

    u_name = html.escape(user_tg.first_name or user_tg.username or "Lector")
    lines = [
        f"📚 <b>Estantes de Lectura de {u_name}</b>",
        f"<i>(Total en seguimiento: {shelves['total_tracked']} obras)</i>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    ]

    reading = shelves["reading"]
    lines.append(f"📖 <b>Leyendo Actualmente ({len(reading)}):</b>")
    if reading:
        for r in reading:
            b_title = html.escape(r.book.title if r.book else "Libro")
            b_auth = html.escape(r.book.author if r.book else "Desconocido")
            bar = format_progress_bar(r.progress_percent, length=8)
            lines.append(f"• <b>{b_title}</b> — <i>{b_auth}</i>\n  Avance: {bar}")
    else:
        lines.append("<i>(No tienes libros en curso actualmente)</i>")
    lines.append("")

    favs = shelves["favorites"]
    lines.append(f"⭐ <b>Mis Favoritos ({len(favs)}):</b>")
    if favs:
        for f in favs:
            f_title = html.escape(f.book.title if f.book else "Libro")
            lines.append(f"• ⭐ <b>{f_title}</b>")
    else:
        lines.append("<i>(Aún no has marcado libros favoritos)</i>")
    lines.append("")

    finished = shelves["finished"]
    lines.append(f"🏆 <b>Terminados ({len(finished)}):</b>")
    if finished:
        for fin in finished[:5]:
            fin_title = html.escape(fin.book.title if fin.book else "Libro")
            lines.append(f"• ✅ <b>{fin_title}</b>")
        if len(finished) > 5:
            lines.append(f"  <i>... y {len(finished) - 5} más</i>")
    else:
        lines.append("<i>(Aún no has marcado libros terminados)</i>")
    lines.append("")

    to_read = shelves["to_read"]
    lines.append(f"📌 <b>Por Leer / Deseos ({len(to_read)}):</b>")
    if to_read:
        for tr in to_read[:5]:
            tr_title = html.escape(tr.book.title if tr.book else "Libro")
            lines.append(f"• 🔖 <b>{tr_title}</b>")
        if len(to_read) > 5:
            lines.append(f"  <i>... y {len(to_read) - 5} más</i>")
    else:
        lines.append("<i>(Tu lista de deseos está vacía)</i>")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Inicia una lectura conjunta con /leerjuntos o actualiza tu progreso con /progreso.</i>")

    card_text = "\n".join(lines)
    try:
        await context.bot.send_message(
            chat_id=chat.id,
            message_thread_id=thread_id,
            text=card_text,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    except Exception:
        await context.bot.send_message(
            chat_id=chat.id,
            text=card_text,
            parse_mode="HTML",
            disable_web_page_preview=True
        )


async def progress_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /progreso <porcentaje> (ej: /progreso 50% o /progreso 40):
    Actualiza rápidamente el avance del usuario en su lectura actual.
    """
    message = update.effective_message
    chat = update.effective_chat
    user_tg = update.effective_user
    if not message or not chat or not user_tg:
        return

    thread_id = getattr(message, "message_thread_id", None)
    args = context.args

    if not args:
        help_p = (
            "📈 <b>Actualización Rápida de Progreso:</b>\n\n"
            "Uso: <code>/progreso &lt;porcentaje&gt;</code>\n\n"
            "<b>Ejemplos:</b>\n"
            "• <code>/progreso 25%</code>\n"
            "• <code>/progreso 50</code>\n"
            "• <code>/progreso 100%</code> <i>(Marca el libro como terminado)</i>"
        )
        await message.reply_text(help_p, parse_mode="HTML")
        return

    raw_val = args[0].replace("%", "").strip()
    try:
        pct = float(raw_val)
    except ValueError:
        await message.reply_text("❌ Por favor indica un número válido (ej: <code>/progreso 45%</code>).", parse_mode="HTML")
        return

    clamped = max(0.0, min(100.0, pct))

    from app.services.buddy_read_service import (
        get_or_create_user_from_telegram,
        update_member_progress,
        update_user_book_state,
        format_progress_bar
    )

    async with AsyncSessionLocal() as session:
        user_db = await get_or_create_user_from_telegram(session, user_tg)

        stmt = (
            select(BuddyReadMember)
            .options(selectinload(BuddyReadMember.buddy_read).selectinload(BuddyRead.book))
            .join(BuddyRead, BuddyReadMember.buddy_read_id == BuddyRead.id)
            .where(
                BuddyReadMember.user_id == user_db.id,
                BuddyRead.status == "active"
            )
            .order_by(BuddyReadMember.last_progress_at.desc())
        )
        res = await session.execute(stmt)
        active_member = res.scalars().first()

        if active_member:
            await update_member_progress(session, active_member.buddy_read_id, user_db.id, clamped)
            b_title = active_member.buddy_read.book.title if active_member.buddy_read and active_member.buddy_read.book else "tu libro"
            bar = format_progress_bar(clamped)
            status_text = "🏆 <b>¡Felicitaciones! Has completado el libro.</b>" if clamped >= 100.0 else "📖 <b>¡Avance registrado exitosamente!</b>"
            await message.reply_text(
                f"{status_text}\n\n"
                f"📚 <b>{html.escape(b_title)}</b>\n"
                f"Tu progreso actual: {bar}",
                parse_mode="HTML"
            )
            return

        stmt_rs = (
            select(ReadingState)
            .options(selectinload(ReadingState.book))
            .where(
                ReadingState.user_id == user_db.id,
                ReadingState.status == "reading"
            )
            .order_by(ReadingState.updated_at.desc())
        )
        res_rs = await session.execute(stmt_rs)
        active_rs = res_rs.scalars().first()

        if active_rs:
            await update_user_book_state(session, user_db.id, active_rs.book_id, progress_percent=clamped)
            b_title = active_rs.book.title if active_rs.book else "tu libro"
            bar = format_progress_bar(clamped)
            status_text = "🏆 <b>¡Felicitaciones! Has completado el libro.</b>" if clamped >= 100.0 else "📖 <b>¡Avance registrado exitosamente!</b>"
            await message.reply_text(
                f"{status_text}\n\n"
                f"📚 <b>{html.escape(b_title)}</b>\n"
                f"Tu progreso actual: {bar}",
                parse_mode="HTML"
            )
            return

        await message.reply_text(
            "ℹ️ No tienes ningún libro marcado como 'leyendo' actualmente.\n"
            "Usa <code>/leerjuntos &lt;título&gt;</code> para empezar a leer con el club.",
            parse_mode="HTML"
        )


async def buddy_read_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja las interacciones de botones en lecturas conjuntas."""
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    parts = data.split(":")
    if len(parts) < 3 or parts[0] != "br":
        return

    action = parts[1]
    chat = update.effective_chat
    user_tg = update.effective_user
    if not chat or not user_tg:
        return

    from app.services.buddy_read_service import (
        get_or_create_user_from_telegram,
        join_buddy_read,
        update_member_progress,
        format_buddy_read_card,
        build_progress_keyboard,
        create_buddy_read,
        find_active_buddy_reads_for_book
    )

    async with AsyncSessionLocal() as session:
        user_db = await get_or_create_user_from_telegram(session, user_tg)

        if action == "start":
            book_id = int(parts[2])
            stmt_b = select(Book).options(selectinload(Book.telegram_link)).where(Book.id == book_id)
            book = (await session.execute(stmt_b)).scalar_one_or_none()
            if not book:
                await query.answer("Libro no encontrado.")
                return

            link = await _get_or_create_link(context.bot, session, chat.id)
            link_id = link.id if link else None

            active_brs = await find_active_buddy_reads_for_book(session, book.id, telegram_link_id=link_id)
            if active_brs:
                br = active_brs[0]
            else:
                br = await create_buddy_read(session, book.id, user_db, telegram_link_id=link_id, tg_user=user_tg)

            card_text, card_kb = format_buddy_read_card(br, book, br.members, chat.id)
            await query.answer("📖 ¡Lectura Conjunta abierta!")
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=getattr(query.message, "message_thread_id", None),
                    text=card_text,
                    reply_markup=card_kb,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=card_text,
                    reply_markup=card_kb,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            return

        br_id = int(parts[2])
        stmt_br = (
            select(BuddyRead)
            .options(selectinload(BuddyRead.members), selectinload(BuddyRead.book).selectinload(Book.telegram_link))
            .where(BuddyRead.id == br_id)
        )
        res = await session.execute(stmt_br)
        br = res.scalar_one_or_none()
        if not br:
            await query.answer("Lectura conjunta no encontrada.")
            return

        async def _load_br(bid: int):
            stmt_reload = (
                select(BuddyRead)
                .options(selectinload(BuddyRead.members), selectinload(BuddyRead.book).selectinload(Book.telegram_link))
                .where(BuddyRead.id == bid)
            )
            return (await session.execute(stmt_reload)).scalar_one()

        if action == "join":
            member, was_created = await join_buddy_read(session, br.id, user_db, tg_user=user_tg)
            if was_created:
                await query.answer("🎉 ¡Te has unido a la lectura conjunta!")
            else:
                await query.answer("Ya estás registrado en esta lectura conjunta.")

            br = await _load_br(br.id)
            card_text, card_kb = format_buddy_read_card(br, br.book, br.members, chat.id)
            try:
                await query.edit_message_text(card_text, reply_markup=card_kb, parse_mode="HTML", disable_web_page_preview=True)
            except Exception:
                pass

        elif action == "prog":
            await query.answer()
            prog_kb = build_progress_keyboard(br.id)
            try:
                await query.edit_message_reply_markup(reply_markup=prog_kb)
            except Exception:
                pass

        elif action == "setp":
            pct = float(parts[3])
            await update_member_progress(session, br.id, user_db.id, pct)
            if pct >= 100.0:
                await query.answer("🏆 ¡Felicitaciones por terminar el libro!")
            else:
                await query.answer(f"📈 Progreso guardado: {int(pct)}%")

            br = await _load_br(br.id)
            card_text, card_kb = format_buddy_read_card(br, br.book, br.members, chat.id)
            try:
                await query.edit_message_text(card_text, reply_markup=card_kb, parse_mode="HTML", disable_web_page_preview=True)
            except Exception:
                pass

        elif action == "incp":
            inc = float(parts[3])
            m = next((mem for mem in br.members if mem.user_id == user_db.id), None)
            cur = m.progress_percent if m else 0.0
            new_pct = min(100.0, cur + inc)
            await update_member_progress(session, br.id, user_db.id, new_pct)
            await query.answer(f"📈 +{int(inc)}% ({int(new_pct)}%)")

            br = await _load_br(br.id)
            card_text, card_kb = format_buddy_read_card(br, br.book, br.members, chat.id)
            try:
                await query.edit_message_text(card_text, reply_markup=card_kb, parse_mode="HTML", disable_web_page_preview=True)
            except Exception:
                pass

        elif action == "card":
            await query.answer()
            br = await _load_br(br.id)
            card_text, card_kb = format_buddy_read_card(br, br.book, br.members, chat.id)
            try:
                await query.edit_message_text(card_text, reply_markup=card_kb, parse_mode="HTML", disable_web_page_preview=True)
            except Exception:
                pass


async def reading_state_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja acciones sobre el estante personal (ej. marcar favorito)."""
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    parts = data.split(":")
    if len(parts) < 3 or parts[0] != "rs":
        return

    action = parts[1]
    book_id = int(parts[2])
    user_tg = update.effective_user
    if not user_tg:
        return

    from app.services.buddy_read_service import (
        get_or_create_user_from_telegram,
        update_user_book_state
    )

    async with AsyncSessionLocal() as session:
        user_db = await get_or_create_user_from_telegram(session, user_tg)

        if action == "fav":
            stmt = select(ReadingState).where(ReadingState.user_id == user_db.id, ReadingState.book_id == book_id)
            st = (await session.execute(stmt)).scalar_one_or_none()
            new_fav = not (st.is_favorite if st else False)
            await update_user_book_state(session, user_db.id, book_id, is_favorite=new_fav)
            msg = "⭐ Añadido a tus Favoritos" if new_fav else "Eliminado de tus Favoritos"
            await query.answer(msg)


