import logging
import re
from datetime import datetime, timezone
from typing import Optional, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
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
from app.services.topic_resolver import resolve_or_create_topic, normalize_genre_slug, delete_topic_by_thread_id
from app.services.ai_classifier import classify_book_with_gemini, get_genre_emoji

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

        # 1.1 Deduplicación Binaria Rápida (file_unique_id)
        file_unique_id = getattr(doc, "file_unique_id", None)
        if file_unique_id:
            stmt_dup = select(Book).where(
                Book.telegram_link_id == link.id,
                Book.file_unique_id == file_unique_id
            )
            dup_res = await session.execute(stmt_dup)
            existing_book = dup_res.scalar_one_or_none()
            if existing_book and existing_book.telegram_message_id:
                logger.info(f"Libro duplicado exacto detectado por file_unique_id: '{existing_book.title}'")
                if link.bot_is_admin:
                    try:
                        await context.bot.delete_message(chat_id=chat.id, message_id=message.message_id)
                    except Exception:
                        pass

                clean_chat_id = str(chat.id).replace("-100", "")
                msg_link = f"https://t.me/c/{clean_chat_id}/{existing_book.telegram_message_id}"
                await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=getattr(message, "message_thread_id", None),
                    text=f"ℹ️ **Este libro ya se encuentra en la biblioteca:**\n\n"
                         f"📖 **{existing_book.title}**\n"
                         f"✍️ *{existing_book.author}*\n"
                         f"🏷️ Tema: **{existing_book.genre}** (`.{existing_book.file_format.upper()}`)\n\n"
                         f"👉 [Pulsa aquí para ir al libro en el tema]({msg_link})",
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
                return

        # 2. Contexto de thread actual y lista de géneros existentes
        current_thread_id = getattr(message, "message_thread_id", None)
        current_topic_hint = None
        if current_thread_id:
            stmt_cur = select(Topic).where(
                Topic.telegram_link_id == link.id,
                Topic.topic_id == current_thread_id
            )
            cur_res = await session.execute(stmt_cur)
            current_topic_obj = cur_res.scalar_one_or_none()
            if current_topic_obj:
                current_topic_hint = current_topic_obj.genre

        stmt_topics = select(Topic).where(Topic.telegram_link_id == link.id)
        topics_res = await session.execute(stmt_topics)
        existing_topics_list = [t.genre for t in topics_res.scalars().all()]

        # 3. Clasificación inteligente con Gemini AI (Zero-friction)
        logger.info(f"Clasificando libro '{filename}' con Gemini AI...")
        classification = await classify_book_with_gemini(
            filename=filename,
            caption=message.caption,
            existing_topics=existing_topics_list,
            current_topic_hint=current_topic_hint
        )

        title = classification["title"]
        author = classification["author"]
        genre = classification["genre"]
        suggested_emoji = classification.get("emoji", "📖")

        # 3.1 Deduplicación Semántica (Título + Formato)
        new_title_slug = normalize_genre_slug(title)
        stmt_books = select(Book).where(Book.telegram_link_id == link.id)
        books_res = await session.execute(stmt_books)
        all_chat_books = books_res.scalars().all()

        matching_book = None
        for b in all_chat_books:
            if normalize_genre_slug(b.title) == new_title_slug:
                matching_book = b
                break

        if matching_book:
            if matching_book.file_format.lower() == ext.lower():
                # Duplicado del mismo formato
                logger.info(f"Libro duplicado semántico detectado: '{matching_book.title}' ({ext})")
                if link.bot_is_admin:
                    try:
                        await context.bot.delete_message(chat_id=chat.id, message_id=message.message_id)
                    except Exception:
                        pass

                clean_chat_id = str(chat.id).replace("-100", "")
                msg_link = f"https://t.me/c/{clean_chat_id}/{matching_book.telegram_message_id}"
                await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=getattr(message, "message_thread_id", None),
                    text=f"ℹ️ **Este libro ya se encuentra en la biblioteca:**\n\n"
                         f"📖 **{matching_book.title}**\n"
                         f"✍️ *{matching_book.author}*\n"
                         f"🏷️ Tema: **{matching_book.genre}** (`.{matching_book.file_format.upper()}`)\n\n"
                         f"👉 [Pulsa aquí para ir al libro en el tema]({msg_link})",
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
                return
            else:
                # Formato complementario (ej: ya había EPUB y ahora suben PDF)
                logger.info(f"Formato complementario para '{matching_book.title}': agrupando {ext} en el tema {matching_book.genre}")
                genre = matching_book.genre

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
            file_unique_id=file_unique_id,
            file_format=ext,
            reading_progress=0.0
        )
        session.add(new_book)
        await session.commit()
        await session.refresh(new_book)

        logger.info(f"Libro registrado: '{new_book.title}' por '{new_book.author}' -> Género: {new_book.genre}")

        # 6. Notificación visual
        clean_chat_id = str(chat.id).replace("-100", "")
        dest_link = f"https://t.me/c/{clean_chat_id}/{target_message_id}"

        # Si el libro fue subido en un tema incorrecto y se reubicó, avisar en el tema origen
        if current_thread_id and assigned_topic_id and current_thread_id != assigned_topic_id:
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=current_thread_id,
                    text=f"🔄 **Libro reubicado automáticamente:**\n\n"
                         f"📖 **{title}** (*{author}*) pertenece a {suggested_emoji} **{genre}**.\n"
                         f"Para mantener la biblioteca ordenada, ha sido trasladado a su tema correspondiente.\n\n"
                         f"👉 [Pulsa aquí para ver el libro en {genre}]({dest_link})",
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
            except Exception as orig_err:
                logger.debug(f"No se pudo enviar aviso de reubicación en origen: {orig_err}")

        # Notificación en el tema de destino
        if assigned_topic_id:
            try:
                if current_thread_id and current_thread_id != assigned_topic_id:
                    dest_text = (
                        f"📚 **Libro sincronizado y archivado:**\n\n"
                        f"📖 **Título:** {title}\n"
                        f"✍️ **Autor:** {author}\n"
                        f"🏷️ **Género:** {suggested_emoji} **{genre}**\n\n"
                        f"*(Reubicado automáticamente desde otro tema donde no correspondía)*"
                    )
                else:
                    dest_text = (
                        f"📚 **Libro sincronizado y archivado:**\n\n"
                        f"📖 **Título:** {title}\n"
                        f"✍️ **Autor:** {author}\n"
                        f"🏷️ **Género:** {suggested_emoji} **{genre}**"
                    )
                await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=assigned_topic_id,
                    text=dest_text,
                    parse_mode="Markdown"
                )
            except Exception as notify_err:
                logger.debug(f"No se pudo enviar mensaje de confirmación: {notify_err}")


def build_catalog_page(chat_id: int, books: List[Book], page: int = 1, per_page: int = 5) -> tuple[str, InlineKeyboardMarkup]:
    """Genera el texto y la botonera de paginación del catálogo de libros."""
    from app.services.ai_classifier import get_genre_emoji

    total_books = len(books)
    total_pages = max(1, (total_books + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_books = books[start_idx:end_idx]

    clean_chat_id = str(chat_id).replace("-100", "")

    lines = [
        "📚 **Catálogo de Libros Disponibles**",
        f"*(Página {page} de {total_pages} — {total_books} libros registrados)*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    ]

    for i, b in enumerate(page_books, start=start_idx + 1):
        emo = get_genre_emoji(b.genre)
        date_str = b.uploaded_at.strftime("%d/%m/%Y") if b.uploaded_at else "Reciente"
        fmt = (b.file_format or "pdf").upper()
        
        msg_link = f"https://t.me/c/{clean_chat_id}/{b.telegram_message_id}" if b.telegram_message_id else None
        link_md = f"[👉 Ver libro]({msg_link})" if msg_link else "*(Sin enlace)*"

        lines.append(
            f"**{i}. 📖 {b.title}**\n"
            f"   ✍️ Autor: *{b.author}*\n"
            f"   🏷️ Tema: {emo} **{b.genre}** (`.{fmt}`)\n"
            f"   📅 Fecha: `{date_str}` | {link_md}\n"
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
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    async with AsyncSessionLocal() as session:
        stmt = select(TelegramLink).where(TelegramLink.chat_id == chat.id)
        res = await session.execute(stmt)
        link = res.scalar_one_or_none()

        if not link:
            await message.reply_text("❌ Este grupo no está vinculado a LibroSync.", parse_mode="Markdown")
            return

        # Consultar libros ordenados por fecha descendente
        stmt_books = select(Book).where(Book.telegram_link_id == link.id).order_by(Book.uploaded_at.desc())
        b_res = await session.execute(stmt_books)
        books = b_res.scalars().all()

        if not books:
            await message.reply_text(
                "📚 **La biblioteca aún está vacía.**\n\n"
                "Sube libros en formato PDF o EPUB al chat para empezar a armar el catálogo.",
                parse_mode="Markdown"
            )
            return

        text, keyboard = build_catalog_page(chat.id, books, page=1)
        await message.reply_text(
            text,
            reply_markup=keyboard,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )


async def catalog_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja los clics de paginación de /libros."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    data = query.data
    if data == "catalog:noop":
        return

    if data.startswith("catalog:page:"):
        page_num = int(data.split(":")[-1])
        chat = update.effective_chat

        async with AsyncSessionLocal() as session:
            stmt = select(TelegramLink).where(TelegramLink.chat_id == chat.id)
            res = await session.execute(stmt)
            link = res.scalar_one_or_none()
            if not link:
                return

            stmt_books = select(Book).where(Book.telegram_link_id == link.id).order_by(Book.uploaded_at.desc())
            b_res = await session.execute(stmt_books)
            books = b_res.scalars().all()

            text, keyboard = build_catalog_page(chat.id, books, page=page_num)
            try:
                await query.edit_message_text(
                    text,
                    reply_markup=keyboard,
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
            except Exception:
                pass


async def topics_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /temas:
    Lista todos los temas activos y cuántos libros tiene cada uno.
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    from app.services.ai_classifier import get_genre_emoji

    async with AsyncSessionLocal() as session:
        stmt = select(TelegramLink).where(TelegramLink.chat_id == chat.id)
        res = await session.execute(stmt)
        link = res.scalar_one_or_none()

        if not link:
            await message.reply_text("❌ Este grupo no está vinculado a LibroSync.", parse_mode="Markdown")
            return

        stmt_topics = select(Topic).where(Topic.telegram_link_id == link.id).order_by(Topic.genre.asc())
        t_res = await session.execute(stmt_topics)
        topics = t_res.scalars().all()

        if not topics:
            await message.reply_text("ℹ️ Aún no hay temas registrados en este grupo.", parse_mode="Markdown")
            return

        # Contar libros por tema
        stmt_books = select(Book).where(Book.telegram_link_id == link.id)
        b_res = await session.execute(stmt_books)
        all_books = b_res.scalars().all()

        counts = {}
        for b in all_books:
            counts[b.genre] = counts.get(b.genre, 0) + 1

        clean_chat_id = str(chat.id).replace("-100", "")

        lines = [
            "🏷️ **Temas y Géneros Disponibles**",
            f"*(Total: {len(topics)} temas en este grupo)*",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        ]

        for t in topics:
            emo = get_genre_emoji(t.genre)
            qty = counts.get(t.genre, 0)
            topic_link = f"https://t.me/c/{clean_chat_id}/{t.topic_id}"
            lines.append(f"• {emo} [**{t.genre}**]({topic_link}) — `{qty} libro(s)`")

        lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("💡 *Pulsa sobre cualquier tema para entrar directamente a él.*")

        await message.reply_text("\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True)


async def topic_index_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /indice:
    Debe ejecutarse DENTRO de un tema. Publica un mensaje índice formateado con todos
    los libros disponibles en este tema específico, con enlaces directos para fijar.
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    thread_id = getattr(message, "message_thread_id", None)
    if not thread_id:
        await message.reply_text("⚠️ Este comando debe ejecutarse **dentro** del tema que deseas indexar.", parse_mode="Markdown")
        return

    from app.services.ai_classifier import get_genre_emoji

    async with AsyncSessionLocal() as session:
        stmt = select(TelegramLink).where(TelegramLink.chat_id == chat.id)
        res = await session.execute(stmt)
        link = res.scalar_one_or_none()

        if not link:
            await message.reply_text("❌ Este grupo no está vinculado a LibroSync.", parse_mode="Markdown")
            return

        # Buscar qué tema corresponde a este thread_id
        stmt_topic = select(Topic).where(
            Topic.telegram_link_id == link.id,
            Topic.topic_id == thread_id
        )
        t_res = await session.execute(stmt_topic)
        topic = t_res.scalar_one_or_none()

        genre_name = topic.genre if topic else "General"
        emo = get_genre_emoji(genre_name)

        # Buscar libros de este tema
        stmt_books = select(Book).where(
            Book.telegram_link_id == link.id,
            Book.genre == genre_name
        ).order_by(Book.title.asc())
        b_res = await session.execute(stmt_books)
        books = b_res.scalars().all()

        clean_chat_id = str(chat.id).replace("-100", "")

        lines = [
            f"📌 **ÍNDICE DE LA COLECCIÓN: {emo} {genre_name}**",
            f"*(Total: {len(books)} libros disponibles)*",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        ]

        if not books:
            lines.append("*(Aún no hay libros archivados en este tema)*\n")
        else:
            for i, b in enumerate(books, start=1):
                fmt = (b.file_format or "pdf").upper()
                msg_link = f"https://t.me/c/{clean_chat_id}/{b.telegram_message_id}" if b.telegram_message_id else None
                link_md = f"[📥 Descargar]({msg_link})" if msg_link else ""
                lines.append(f"**{i}.** 📖 **{b.title}** — *{b.author}* (`.{fmt}`) {link_md}")

        lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("💡 *Tip para Administradores: Fija este mensaje en el tema para que los lectores lo vean al entrar.*")

        await message.reply_text("\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True)


async def register_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /registrar o /indexar:
    Permite catalogar libros antiguos que ya estaban en el chat antes de que el bot se agregara.
    El usuario responde a un mensaje antiguo que tenga un PDF/EPUB con `/registrar`.
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    if not message.reply_to_message or not message.reply_to_message.document:
        await message.reply_text(
            "⚠️ **Modo de Uso:**\n"
            "Responde a un mensaje antiguo que contenga un libro (PDF o EPUB) escribiendo `/registrar`.",
            parse_mode="Markdown"
        )
        return

    target_msg = message.reply_to_message
    doc = target_msg.document
    filename = doc.file_name or "libro_antiguo"
    base_raw, ext = clean_filename(filename)

    if f".{ext}" not in SUPPORTED_EXTENSIONS:
        await message.reply_text(f"⚠️ Extensión `.{ext}` no soportada.", parse_mode="Markdown")
        return

    status_msg = await message.reply_text("⏳ Procesando libro antiguo con Gemini AI...")

    try:
        async with AsyncSessionLocal() as session:
            stmt = select(TelegramLink).where(TelegramLink.chat_id == chat.id)
            res = await session.execute(stmt)
            link = res.scalar_one_or_none()

            if not link:
                await status_msg.edit_text("❌ Este grupo no está vinculado a LibroSync.")
                return

            # 1. Comprobar si ya existe en BD por file_unique_id
            file_unique_id = getattr(doc, "file_unique_id", None)
            existing_book = None
            if file_unique_id:
                stmt_dup = select(Book).where(
                    Book.telegram_link_id == link.id,
                    Book.file_unique_id == file_unique_id
                )
                dup_res = await session.execute(stmt_dup)
                existing_book = dup_res.scalar_one_or_none()

            # 2. Contexto del thread actual (dónde se ejecutó el comando o está el mensaje)
            current_thread_id = getattr(target_msg, "message_thread_id", None) or getattr(message, "message_thread_id", None)
            current_topic_hint = None
            if current_thread_id:
                stmt_cur = select(Topic).where(
                    Topic.telegram_link_id == link.id,
                    Topic.topic_id == current_thread_id
                )
                cur_res = await session.execute(stmt_cur)
                current_topic_obj = cur_res.scalar_one_or_none()
                if current_topic_obj:
                    current_topic_hint = current_topic_obj.genre

            # 3. Consultar temas existentes en este grupo
            stmt_topics = select(Topic).where(Topic.telegram_link_id == link.id)
            topics_res = await session.execute(stmt_topics)
            existing_topics_list = [t.genre for t in topics_res.scalars().all()]

            # 4. Clasificar con Gemini (detección objetiva del género real)
            classification = await classify_book_with_gemini(
                filename=filename,
                caption=target_msg.caption,
                existing_topics=existing_topics_list,
                current_topic_hint=current_topic_hint
            )

            title = classification["title"]
            author = classification["author"]
            genre = classification["genre"]
            suggested_emoji = classification.get("emoji", "📖")

            # Caso 4.1: El libro ya estaba en BD pero con un género erróneo -> Reclasificar y Reubicar
            if existing_book and existing_book.telegram_message_id:
                if normalize_genre_slug(existing_book.genre) == normalize_genre_slug(genre):
                    clean_chat_id = str(chat.id).replace("-100", "")
                    msg_link = f"https://t.me/c/{clean_chat_id}/{existing_book.telegram_message_id}"
                    await status_msg.edit_text(
                        f"ℹ️ **Este libro ya se encuentra correctamente registrado en la biblioteca:**\n\n"
                        f"📖 **{existing_book.title}**\n"
                        f"✍️ *{existing_book.author}*\n"
                        f"🏷️ Tema: **{existing_book.genre}** (`.{existing_book.file_format.upper()}`)\n\n"
                        f"👉 [Pulsa aquí para ir al libro en el tema]({msg_link})",
                        parse_mode="Markdown",
                        disable_web_page_preview=True
                    )
                    return
                else:
                    # El género cambió: mover al tema correcto
                    logger.info(f"Reclasificando libro '{existing_book.title}': de '{existing_book.genre}' a '{genre}'")
                    old_genre_name = existing_book.genre
                    target_message_id = existing_book.telegram_message_id

                    if link.forum_enabled:
                        topic_id = await resolve_or_create_topic(
                            session=session,
                            bot=context.bot,
                            telegram_link=link,
                            genre=genre,
                            suggested_emoji=suggested_emoji
                        )
                        if topic_id and current_thread_id != topic_id:
                            try:
                                reposted_id = await move_or_repost_to_topic(
                                    bot=context.bot,
                                    chat_id=chat.id,
                                    message_id=target_msg.message_id,
                                    topic_id=topic_id,
                                    delete_original=link.bot_is_admin
                                )
                                if reposted_id:
                                    target_message_id = reposted_id
                            except ThreadNotFoundError:
                                await delete_topic_by_thread_id(session, link.id, topic_id)
                                emoji = get_genre_emoji(genre, suggested_emoji)
                                new_created = await context.bot.create_forum_topic(chat_id=chat.id, name=f"{emoji} {genre}"[:128])
                                new_topic = Topic(telegram_link_id=link.id, genre=genre, topic_id=new_created.message_thread_id)
                                session.add(new_topic)
                                await session.commit()
                                await session.refresh(new_topic)
                                reposted_id = await move_or_repost_to_topic(
                                    bot=context.bot,
                                    chat_id=chat.id,
                                    message_id=target_msg.message_id,
                                    topic_id=new_created.message_thread_id,
                                    delete_original=link.bot_is_admin
                                )
                                if reposted_id:
                                    target_message_id = reposted_id

                    existing_book.title = title
                    existing_book.author = author
                    existing_book.genre = genre
                    existing_book.telegram_message_id = target_message_id
                    await session.commit()
                    await session.refresh(existing_book)

                    clean_chat_id = str(chat.id).replace("-100", "")
                    link_url = f"https://t.me/c/{clean_chat_id}/{target_message_id}"
                    await status_msg.edit_text(
                        f"🔄 **¡Libro reclasificado y reubicado con éxito!**\n\n"
                        f"📖 **Título:** {title}\n"
                        f"✍️ **Autor:** {author}\n"
                        f"🏷️ **Tema anterior:** {old_genre_name}\n"
                        f"🏷️ **Nuevo tema corregido:** {suggested_emoji} **{genre}** (`.{ext.upper()}`)\n\n"
                        f"*(El libro fue trasladado a su tema correspondiente)*\n\n"
                        f"👉 [Ir al libro en {genre}]({link_url})",
                        parse_mode="Markdown",
                        disable_web_page_preview=True
                    )
                    return

            # 4.2 Deduplicación Semántica (Título + Formato)
            new_title_slug = normalize_genre_slug(title)
            stmt_books = select(Book).where(Book.telegram_link_id == link.id)
            books_res = await session.execute(stmt_books)
            all_chat_books = books_res.scalars().all()

            matching_book = None
            for b in all_chat_books:
                if normalize_genre_slug(b.title) == new_title_slug:
                    matching_book = b
                    break

            if matching_book:
                if matching_book.file_format.lower() == ext.lower():
                    if normalize_genre_slug(matching_book.genre) == normalize_genre_slug(genre):
                        clean_chat_id = str(chat.id).replace("-100", "")
                        msg_link = f"https://t.me/c/{clean_chat_id}/{matching_book.telegram_message_id}"
                        await status_msg.edit_text(
                            f"ℹ️ **Este libro ya se encuentra registrado en la biblioteca:**\n\n"
                            f"📖 **{matching_book.title}**\n"
                            f"✍️ *{matching_book.author}*\n"
                            f"🏷️ Tema: **{matching_book.genre}** (`.{matching_book.file_format.upper()}`)\n\n"
                            f"👉 [Pulsa aquí para ir al libro en el tema]({msg_link})",
                            parse_mode="Markdown",
                            disable_web_page_preview=True
                        )
                        return
                else:
                    # Formato complementario (ej: ya había EPUB y ahora registran PDF)
                    genre = matching_book.genre

            # 5. Comprobar si ya está en el topic correcto o si debe moverse/copiarse
            target_message_id = target_msg.message_id
            assigned_topic_id = current_thread_id

            if link.forum_enabled:
                topic_id = await resolve_or_create_topic(
                    session=session,
                    bot=context.bot,
                    telegram_link=link,
                    genre=genre,
                    suggested_emoji=suggested_emoji
                )
                assigned_topic_id = topic_id

                # Si el libro viejo no estaba en el topic asignado, moverlo allí
                if topic_id and current_thread_id != topic_id:
                    try:
                        reposted_id = await move_or_repost_to_topic(
                            bot=context.bot,
                            chat_id=chat.id,
                            message_id=target_msg.message_id,
                            topic_id=topic_id,
                            delete_original=link.bot_is_admin  # Si es admin, limpiar el tema incorrecto
                        )
                        if reposted_id:
                            target_message_id = reposted_id
                    except ThreadNotFoundError:
                        # Auto-recuperación si el topic en Telegram fue eliminado
                        logger.warning(f"Topic {topic_id} fue eliminado en Telegram. Auto-creando nuevo topic para '{genre}'...")
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
                            message_id=target_msg.message_id,
                            topic_id=new_created.message_thread_id,
                            delete_original=link.bot_is_admin
                        )
                        if reposted_id:
                            target_message_id = reposted_id

            # 6. Registrar en Base de Datos
            new_book = Book(
                user_id=link.user_id,
                title=title,
                author=author,
                genre=genre,
                source="telegram",
                telegram_link_id=link.id,
                telegram_message_id=target_message_id,
                telegram_file_id=doc.file_id,
                file_unique_id=getattr(doc, "file_unique_id", None),
                file_format=ext,
                reading_progress=0.0
            )
            session.add(new_book)
            await session.commit()
            await session.refresh(new_book)

            clean_chat_id = str(chat.id).replace("-100", "")
            link_url = f"https://t.me/c/{clean_chat_id}/{target_message_id}"

            if current_thread_id and assigned_topic_id and current_thread_id != assigned_topic_id:
                status_text = (
                    f"🔄 **¡Libro detectado y reubicado con éxito!**\n\n"
                    f"📖 **Título:** {title}\n"
                    f"✍️ **Autor:** {author}\n"
                    f"🏷️ **Tema asignado:** {suggested_emoji} **{genre}** (`.{ext.upper()}`)\n\n"
                    f"*(El libro estaba ubicado en otro tema y fue trasladado automáticamente a {genre})*\n\n"
                    f"👉 [Ir al libro en {genre}]({link_url})"
                )
            else:
                status_text = (
                    f"✅ **¡Libro antiguo registrado con éxito!**\n\n"
                    f"📖 **Título:** {title}\n"
                    f"✍️ **Autor:** {author}\n"
                    f"🏷️ **Tema:** {suggested_emoji} **{genre}** (`.{ext.upper()}`)\n\n"
                    f"👉 [Ir al libro]({link_url})"
                )

            await status_msg.edit_text(
                status_text,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
    except Exception as e:
        logger.error(f"Error registrando libro antiguo en chat {chat.id}: {e}", exc_info=True)
        try:
            await status_msg.edit_text(
                f"❌ **No se pudo registrar el libro:**\n`{str(e)[:250]}`\n\n"
                "Por favor, intenta de nuevo.",
                parse_mode="Markdown"
            )
        except Exception:
            pass


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra la guía completa de comandos disponibles."""
    message = update.effective_message
    if not message:
        return

    help_text = (
        "🤖 **Comandos Disponibles en Griffin — LibroSync:**\n\n"
        "📚 **Biblioteca & Catálogo:**\n"
        "• `/libros` o `/catalogo` — Lista paginada de todos los libros con autor, fecha, tema y enlaces de descarga.\n"
        "• `/temas` — Ver todos los géneros registrados en el grupo con conteo de libros.\n"
        "• `/indice` — *(Ejecutar dentro de un tema)* Genera y publica la lista ordenada de libros de ese tema para fijar.\n\n"
        "⚙️ **Administración & Organización:**\n"
        "• `/registrar` — Responde a un mensaje antiguo que tenga un PDF o EPUB para clasificarlo e indexarlo de inmediato.\n"
        "• `/settopic <Género>` — *(Ejecutar dentro de un tema)* Asigna ese tema manualmente a un género específico.\n"
        "• `/start` — Ver estado del bot o vincular el grupo a la app LibroSync.\n"
        "• `/help` — Ver este menú de ayuda.\n\n"
        "✨ **Modo Cero Fricción:** No necesitas comandos para subir libros nuevos: ¡solo arrastra cualquier PDF o EPUB al chat y Griffin se encarga de todo!"
    )
    await message.reply_text(help_text, parse_mode="Markdown")
