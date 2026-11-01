from __future__ import annotations
import asyncio
import logging
import re
import html
import secrets
import string
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple, Any

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


async def _get_or_create_link(bot, session, chat_id: int, effective_user=None) -> Optional[TelegramLink]:
    """
    Obtiene el vínculo existente para un chat.
    En chat privado (chat_id > 0), auto-inicializa la biblioteca personal si no existe.
    En grupos (chat_id < 0), solo retorna el vínculo si el grupo fue vinculado previamente con un código válido.
    """
    stmt = select(TelegramLink).where(TelegramLink.chat_id == chat_id)
    res = await session.execute(stmt)
    link = res.scalar_one_or_none()
    if not link:
        if chat_id > 0:
            # Chat privado: auto-vincular como biblioteca personal
            tg_user_id = effective_user.id if effective_user else chat_id
            stmt_u = select(User).where(User.telegram_user_id == tg_user_id)
            user_res = await session.execute(stmt_u)
            user = user_res.scalar_one_or_none()
            if not user:
                user_name = (
                    effective_user.full_name or effective_user.first_name
                    if effective_user else "Usuario Personal"
                )
                user = User(telegram_user_id=tg_user_id, nombre=user_name)
                session.add(user)
                await session.commit()
                await session.refresh(user)

            link = TelegramLink(
                user_id=user.id,
                chat_id=chat_id,
                chat_type="private",
                chat_title=f"Biblioteca Personal ({user.nombre})",
                bot_is_admin=True,
                forum_enabled=False
            )
            session.add(link)
            await session.commit()
            await session.refresh(link)
            return link
        else:
            # Grupo no vinculado: NO auto-vincular a ciegas sin código
            return None
    return link


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Maneja el comando /start [codigo_vinculacion]
    Permite configurar el bot para Biblioteca Personal o vincular una Biblioteca de Grupo con código único.
    """
    message = update.effective_message
    chat = update.effective_chat
    tg_user = update.effective_user

    if not message or not chat:
        return

    args = context.args
    bot = context.bot

    # Caso 1: /start sin argumentos
    if not args:
        if chat.type == "private":
            user_name = html.escape(tg_user.first_name if tg_user else "lector")
            keyboard = [
                [InlineKeyboardButton("👤 Biblioteca Personal", callback_data="setup_mode:personal")],
                [InlineKeyboardButton("👥 Biblioteca de Grupo", callback_data="setup_mode:group")],
            ]
            welcome_text = (
                f"✨ <b>¡Hola, {user_name}! Bienvenido a Griffin</b> 📖\n"
                "<i>Tu bibliotecario digital inteligente y compañero de lectura.</i>\n\n"
                "Estoy aquí para gestionar tu colección de libros, organizar clubes de lectura y acompañarte en cada página sin complicaciones.\n\n"
                "<b>¿Cómo deseas utilizarme?</b>\n\n"
                "👤 <b>Biblioteca Personal:</b>\n"
                "Tu espacio privado. Envíame cualquier PDF o EPUB a este chat y armaré tu catálogo exclusivo, con registro de avance y estantes personales.\n\n"
                "👥 <b>Biblioteca de Grupo:</b>\n"
                "La biblioteca de tu comunidad o club de lectura. Generaremos un <b>código único de vinculación</b> para organizar los libros por temas/géneros y leer en equipo con aislamiento total de datos.\n\n"
                "👇 <i>Selecciona una opción para comenzar:</i>"
            )
            await message.reply_text(welcome_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        else:
            # En grupo / supergrupo sin argumentos
            async with AsyncSessionLocal() as session:
                stmt_link = select(TelegramLink).where(TelegramLink.chat_id == chat.id)
                res_link = await session.execute(stmt_link)
                existing_link = res_link.scalar_one_or_none()

                if existing_link:
                    stmt_count = select(Book).where(Book.telegram_link_id == existing_link.id)
                    res_count = await session.execute(stmt_count)
                    total_books = len(res_count.scalars().all())

                    stmt_topics = select(Topic).where(Topic.telegram_link_id == existing_link.id)
                    res_topics = await session.execute(stmt_topics)
                    total_topics = len(res_topics.scalars().all())

                    safe_title = html.escape(existing_link.chat_title or chat.title or "Grupo")
                    msg = (
                        f"👋 <b>¡Hola a todos! Soy Griffin, el bibliotecario de '{safe_title}'</b> 📚✨\n\n"
                        f"• 📖 <b>Libros registrados:</b> {total_books} obras\n"
                        f"• 🏷️ <b>Estantes temáticos:</b> {total_topics} géneros activos\n"
                        f"• 🔒 <b>Privacidad:</b> Biblioteca aislada y protegida al 100%\n\n"
                        "🚀 <b>Comandos rápidos:</b>\n"
                        "• <code>/buscar &lt;título o autor&gt;</code> — Buscar libros en el catálogo\n"
                        "• <code>/libros</code> — Ver catálogo interactivo de este grupo\n"
                        "• <code>/temas</code> — Ver estantes temáticos disponibles\n"
                        "• <code>/leerjuntos</code> — Iniciar o unirse a una lectura conjunta\n"
                        "• <code>/mislibros</code> — Ver mi perfil de lector y co-lectores\n"
                        "• <code>/help</code> — Ver guía completa de comandos\n\n"
                        "✨ <i>¡Sube o reenvía cualquier PDF o EPUB al chat y Griffin lo catalogará y archivará en su tema correspondiente al instante!</i>"
                    )
                    await message.reply_text(msg, parse_mode="HTML")
                    return
                else:
                    bot_username = (await bot.get_me()).username
                    msg = (
                        "👋 <b>¡Saludos! Soy Griffin, tu bibliotecario digital inteligente.</b> 📚✨\n\n"
                        "Para activar y vincular la biblioteca comunitaria de este grupo:\n"
                        f"1. Abre un chat privado con @{bot_username}.\n"
                        "2. Envía <code>/start</code> y selecciona <b>'👥 Biblioteca de Grupo'</b>.\n"
                        "3. Elige la duración del código de vinculación y envíalo aquí con:\n"
                        "<code>/start &lt;CÓDIGO&gt;</code>\n\n"
                        "💡 <i>Recomendación: Activa los <b>Temas/Topics</b> en este grupo y concédeme permisos de administrador para clasificar y mover los libros por género automáticamente.</i>"
                    )
                    await message.reply_text(msg, parse_mode="HTML")
                    return

    # Caso 2: /start <codigo>
    code_str = args[0].strip()

    async with AsyncSessionLocal() as session:
        stmt = select(LinkCode).where(LinkCode.code == code_str)
        res = await session.execute(stmt)
        link_code = res.scalar_one_or_none()

        if not link_code:
            await message.reply_text(
                "⚠️ <b>Código inválido.</b>\n"
                "Por favor verifica el código o genera uno nuevo en el chat privado con el bot.",
                parse_mode="HTML"
            )
            return

        now_utc = datetime.now(timezone.utc)
        exp = link_code.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)

        if now_utc > exp:
            await message.reply_text(
                "⏳ <b>Este código de vinculación ha expirado.</b>\n"
                "Por favor genera un código nuevo en el chat privado con el bot.",
                parse_mode="HTML"
            )
            return

        try:
            status_info = await get_chat_and_bot_status(bot, chat.id)
        except Exception as e:
            await message.reply_text(f"❌ Error al consultar información del chat: {html.escape(str(e))}", parse_mode="HTML")
            return

        chat_type_str = "group_forum" if status_info["forum_enabled"] else status_info["chat_type"]

        stmt_link = select(TelegramLink).where(TelegramLink.chat_id == chat.id)
        res_link = await session.execute(stmt_link)
        existing_link = res_link.scalar_one_or_none()

        safe_title = html.escape(status_info["chat_title"] or chat.title or "Grupo")

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

        await session.commit()

        msg_lines = [
            f"🎉 <b>¡Grupo '{safe_title}' vinculado exitosamente!</b>\n",
            f"• <b>Tipo:</b> <code>{chat_type_str}</code>",
            f"• <b>Temas (Topics):</b> {'✅ Activado' if status_info['forum_enabled'] else '⚠️ Desactivado (activa temas para organizar por géneros)'}",
            f"• <b>Bot Administrador:</b> {'✅ Sí' if status_info['bot_is_admin'] else '❌ No (haz al bot administrador)'}",
            f"• <b>Permiso 'Administrar temas':</b> {'✅ Sí' if status_info.get('can_manage_topics') else '⚠️ No asignado'}\n",
            "🔒 <b>Aislamiento Garantizado:</b> Este grupo cuenta con su propia biblioteca independiente. Ningún libro ni dato se mezcla con otros grupos ni con chats privados.\n",
            "✨ <b>Modo Cero Fricción:</b> Puedes enviar libros directamente y Griffin los clasificará y moverá a su tema correspondiente de forma automática."
        ]
        await message.reply_text("\n".join(msg_lines), parse_mode="HTML")


async def setup_mode_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección inicial de modo: Personal o Grupo."""
    query = update.callback_query
    await query.answer()
    data = query.data
    chat = update.effective_chat
    tg_user = update.effective_user

    if data == "setup_mode:personal":
        async with AsyncSessionLocal() as session:
            stmt_u = select(User).where(User.telegram_user_id == tg_user.id)
            user = (await session.execute(stmt_u)).scalar_one_or_none()
            if not user:
                user = User(
                    telegram_user_id=tg_user.id,
                    nombre=tg_user.full_name or tg_user.first_name or "Usuario Personal"
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)

            stmt_l = select(TelegramLink).where(TelegramLink.chat_id == chat.id)
            link = (await session.execute(stmt_l)).scalar_one_or_none()
            if not link:
                link = TelegramLink(
                    user_id=user.id,
                    chat_id=chat.id,
                    chat_type="private",
                    chat_title=f"Biblioteca Personal de {user.nombre}",
                    bot_is_admin=True,
                    forum_enabled=False
                )
                session.add(link)
            else:
                link.chat_type = "private"
                link.user_id = user.id
            await session.commit()

        msg = (
            "👤 <b>¡Biblioteca Personal Activada!</b>\n\n"
            "Este chat privado es ahora tu estante personal e independiente:\n\n"
            "• 📥 <b>Sube tus libros:</b> Envíame cualquier PDF, EPUB, MOBI, CBR o CBZ aquí y lo clasificaré con IA.\n"
            "• 📚 <b>Catálogo:</b> Usa <code>/libros</code> para ver todos tus libros organizados.\n"
            "• 🔍 <b>Búsqueda:</b> Usa <code>/buscar &lt;título o autor&gt;</code> para encontrar obras al instante.\n"
            "• 🏷️ <b>Géneros:</b> Usa <code>/temas</code> para explorar tus lecturas por género.\n"
            "• 📖 <b>Seguimiento:</b> Usa <code>/mislibros</code> y <code>/progreso &lt;%&gt;</code> para registrar tu avance de lectura.\n\n"
            "✨ <i>¡Envíame un libro ahora mismo para comenzar tu colección personal!</i>"
        )
        keyboard = [
            [InlineKeyboardButton("📚 Ver Catálogo", callback_data="catalog:page:1")],
            [InlineKeyboardButton("👥 Configurar también un Grupo", callback_data="setup_mode:group")]
        ]
        await query.edit_message_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "setup_mode:group":
        keyboard = [
            [
                InlineKeyboardButton("⏱️ 1 Hora", callback_data="code_exp:1h"),
                InlineKeyboardButton("📅 24 Horas", callback_data="code_exp:24h"),
            ],
            [
                InlineKeyboardButton("🗓️ 7 Días", callback_data="code_exp:7d"),
                InlineKeyboardButton("📆 30 Días", callback_data="code_exp:30d"),
            ],
            [
                InlineKeyboardButton("♾️ Permanente (Sin Expiración)", callback_data="code_exp:never")
            ],
            [
                InlineKeyboardButton("⬅️ Volver", callback_data="setup_mode:back")
            ]
        ]
        msg = (
            "👥 <b>Configuración de Biblioteca de Grupo</b>\n\n"
            "Para vincular un grupo o club de lectura, generaremos un <b>código único de vinculación</b>.\n\n"
            "⏱️ <b>Selecciona la vigencia / fecha de expiración para tu código:</b>\n"
            "<i>(Podrás usar este código para vincular uno o varios grupos antes de que expire. Cada grupo mantendrá su biblioteca 100% aislada de los demás)</i>"
        )
        await query.edit_message_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "setup_mode:back":
        user_name = html.escape(tg_user.first_name if tg_user else "lector")
        keyboard = [
            [InlineKeyboardButton("👤 Biblioteca Personal", callback_data="setup_mode:personal")],
            [InlineKeyboardButton("👥 Biblioteca de Grupo", callback_data="setup_mode:group")],
        ]
        welcome_text = (
            f"👋 <b>Soy Griffin, tu bibliotecario digital inteligente.</b>\n\n"
            "📚 ¿Cómo deseas utilizarme hoy?\n\n"
            "1️⃣ <b>Biblioteca Personal:</b>\n"
            "Guarda y organiza tus libros directamente en este chat privado.\n\n"
            "2️⃣ <b>Biblioteca de Grupo:</b>\n"
            "Organiza la biblioteca de tu club de lectura en un grupo con <b>Temas/Topics</b>.\n\n"
            "👇 <i>Selecciona una opción:</i>"
        )
        await query.edit_message_text(welcome_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


async def code_exp_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Genera el código único con la fecha de expiración elegida por el usuario."""
    query = update.callback_query
    await query.answer()
    data = query.data
    tg_user = update.effective_user
    bot = context.bot

    duration_key = data.replace("code_exp:", "")
    now_utc = datetime.now(timezone.utc)

    if duration_key == "1h":
        expires_at = now_utc + timedelta(hours=1)
        exp_label = "1 Hora"
    elif duration_key == "24h":
        expires_at = now_utc + timedelta(days=1)
        exp_label = "24 Horas"
    elif duration_key == "7d":
        expires_at = now_utc + timedelta(days=7)
        exp_label = "7 Días"
    elif duration_key == "30d":
        expires_at = now_utc + timedelta(days=30)
        exp_label = "30 Días"
    else:  # "never"
        expires_at = datetime(2099, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        exp_label = "Permanente (Sin Expiración)"

    chars = string.ascii_uppercase + string.digits
    rand_part = "".join(secrets.choice(chars) for _ in range(6))
    code_str = f"GRP-{rand_part}"

    async with AsyncSessionLocal() as session:
        stmt_u = select(User).where(User.telegram_user_id == tg_user.id)
        user = (await session.execute(stmt_u)).scalar_one_or_none()
        if not user:
            user = User(
                telegram_user_id=tg_user.id,
                nombre=tg_user.full_name or tg_user.first_name or "Administrador"
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

        link_code = LinkCode(
            code=code_str,
            user_id=user.id,
            expires_at=expires_at,
            used=False
        )
        session.add(link_code)
        await session.commit()

    bot_me = await bot.get_me()
    deep_link = f"https://t.me/{bot_me.username}?startgroup={code_str}"
    exp_date_str = expires_at.strftime("%d/%m/%Y %H:%M UTC") if duration_key != "never" else "Nunca (Permanente)"

    msg = (
        "🎉 <b>¡Código de Vinculación de Grupo Generado!</b>\n\n"
        f"• <b>Código Único:</b> <code>{code_str}</code>\n"
        f"• <b>Vigencia:</b> {exp_label}\n"
        f"• <b>Expira el:</b> {exp_date_str}\n\n"
        "📋 <b>Pasos para vincular tu grupo:</b>\n"
        f"1. Pulsa el botón de abajo <b>'➕ Añadir a mi Grupo'</b> (o añade a @{bot_me.username} como admin).\n"
        "2. Asegúrate de que el grupo tenga <b>Temas/Topics activados</b>.\n"
        "3. Dale permiso de administrador con <b>'Administrar temas'</b>.\n"
        f"4. Si lo añadiste manualmente, envía en el grupo: <code>/start {code_str}</code>\n\n"
        "🔒 <b>Aislamiento Garantizado:</b> Cada grupo vinculado tendrá su propia biblioteca totalmente independiente. Ningún libro ni catálogo se mezclará con otros grupos ni con tu biblioteca personal."
    )

    keyboard = [
        [InlineKeyboardButton("➕ Añadir a mi Grupo", url=deep_link)],
        [InlineKeyboardButton("🔄 Generar otro código", callback_data="setup_mode:group")],
        [InlineKeyboardButton("👤 Ver mi Biblioteca Personal", callback_data="setup_mode:personal")]
    ]
    await query.edit_message_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))



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



def build_catalog_page(chat_id: int, books: List[Book], page: int = 1, per_page: int = 5, topic_id: Optional[int] = None, genre_name: Optional[str] = None) -> tuple[str, InlineKeyboardMarkup]:
    """Genera el texto y la botonera de paginación del catálogo de libros con formato HTML seguro."""
    import html
    from app.services.ai_classifier import get_genre_emoji

    total_books = len(books)
    total_pages = max(1, (total_books + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_books = books[start_idx:end_idx]

    if genre_name:
        emo = get_genre_emoji(genre_name)
        header_title = f"📚 <b>Catálogo: {emo} {html.escape(genre_name)}</b>"
    else:
        header_title = "📚 <b>Catálogo de Libros Disponibles</b>"

    lines = [
        header_title,
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
    prefix = f"catalog:t:{topic_id}:" if topic_id else "catalog:page:"
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"{prefix}{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="catalog:noop"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"{prefix}{page + 1}"))

    keyboard = InlineKeyboardMarkup([nav_buttons]) if total_pages > 1 else InlineKeyboardMarkup([[]])
    return "\n".join(lines), keyboard


async def catalog_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /libros o /catalogo:
    Muestra la lista paginada de libros disponibles con título, autor, fecha, género y enlace directo.
    Funciona tanto en el tema General como dentro de cualquier tema o en chats privados.
    Si se ejecuta dentro de un tema específico, muestra los libros de ese tema.
    Para ver la biblioteca completa desde un tema: /libros todos.
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
                text="❌ Este grupo no está vinculado a una biblioteca. Usa /start para ver opciones de vinculación.",
                parse_mode="HTML"
            )
            return

        # Comprobar si se pide ver toda la biblioteca explícitamente o si estamos en un tema particular
        arg_all = context.args and any("todo" in a.lower() for a in context.args)
        topic_filter = None
        topic_id_val = None
        if thread_id and not arg_all:
            stmt_t = select(Topic).where(Topic.telegram_link_id == link.id, Topic.topic_id == thread_id)
            t_res = await session.execute(stmt_t)
            topic_obj = t_res.scalar_one_or_none()
            if topic_obj:
                topic_filter = topic_obj.genre
                topic_id_val = thread_id

        # Consultar libros con aislamiento estricto por biblioteca/chat
        book_filter = (
            or_(Book.telegram_link_id == link.id, Book.user_id == link.user_id)
            if link.chat_type == "private"
            else (Book.telegram_link_id == link.id)
        )
        stmt_books = (
            select(Book)
            .options(selectinload(Book.telegram_link))
            .where(book_filter)
        )

        if topic_filter:
            stmt_books = stmt_books.where(Book.genre == topic_filter)

        stmt_books = stmt_books.order_by(Book.uploaded_at.desc())
        b_res = await session.execute(stmt_books)
        books = b_res.scalars().all()

        if not books:
            empty_text = (
                f"📚 <b>No hay libros en '{topic_filter}'.</b>\n\nSube libros a este tema para verlos aquí."
                if topic_filter else
                "📚 <b>La biblioteca aún está vacía.</b>\n\nSube libros en formato PDF o EPUB al chat o a cualquier tema para empezar a armar el catálogo."
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

        text, keyboard = build_catalog_page(chat.id, books, page=1, topic_id=topic_id_val, genre_name=topic_filter)
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
    """Maneja los clics de paginación de /libros sin saturar el chat."""
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

    chat = update.effective_chat
    if not chat:
        return

    topic_id_val = None
    topic_filter = None
    page_num = 1

    if data.startswith("catalog:t:"):
        parts = data.split(":")
        topic_id_val = int(parts[2])
        page_num = int(parts[3])
    elif data.startswith("catalog:page:"):
        page_num = int(data.split(":")[-1])
    else:
        return

    async with AsyncSessionLocal() as session:
        link = await _get_or_create_link(context.bot, session, chat.id)
        if not link:
            return

        if topic_id_val:
            stmt_t = select(Topic).where(Topic.telegram_link_id == link.id, Topic.topic_id == topic_id_val)
            t_res = await session.execute(stmt_t)
            topic_obj = t_res.scalar_one_or_none()
            if topic_obj:
                topic_filter = topic_obj.genre

        book_filter = (
            or_(Book.telegram_link_id == link.id, Book.user_id == link.user_id)
            if link.chat_type == "private"
            else (Book.telegram_link_id == link.id)
        )
        stmt_books = (
            select(Book)
            .options(selectinload(Book.telegram_link))
            .where(book_filter)
        )

        if topic_filter:
            stmt_books = stmt_books.where(Book.genre == topic_filter)

        stmt_books = stmt_books.order_by(Book.uploaded_at.desc())
        b_res = await session.execute(stmt_books)
        books = b_res.scalars().all()

        text, keyboard = build_catalog_page(chat.id, books, page=page_num, topic_id=topic_id_val, genre_name=topic_filter)
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
            "🔍 <b>Búsqueda en la Biblioteca Digital:</b>\n\n"
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
                text="❌ Este grupo no está vinculado a una biblioteca. Usa /start para ver opciones de vinculación.",
                parse_mode="HTML"
            )
            return

        # Consultar libros (en privado consulta los del usuario, en grupo los del grupo)
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


_DOWNLOAD_CACHE_TTL_SECONDS = 2 * 60 * 60
_DOWNLOAD_PAGE_SIZE = 5
_download_cache: Dict[str, Dict[str, Any]] = {}  # token -> {results, created, query}
_DOWNLOAD_FORMAT_ORDER = {"epub": 0, "pdf": 1, "mobi": 2, "azw3": 3, "cbz": 4, "cbr": 5}
_DOWNLOAD_FORMAT_ICONS = {
    "epub": "📗",
    "pdf": "📄",
    "mobi": "📘",
    "azw3": "📘",
    "cbz": "📦",
    "cbr": "📦",
}
_DOWNLOAD_SOURCE_SHORT = {
    "Internet Archive": "Archive",
    "Open Library": "OpenLib",
    "Project Gutenberg": "Gutenberg",
    "Library Genesis": "LibGen",
}


def _cleanup_download_cache(now: Optional[float] = None) -> None:
    """Elimina solicitudes de descarga caducadas para no acumular memoria."""
    current = time.time() if now is None else now
    for token in list(_download_cache.keys()):
        entry = _download_cache.get(token) or {}
        try:
            created = float(entry.get("created", 0))
        except (TypeError, ValueError):
            created = 0
        if current - created > _DOWNLOAD_CACHE_TTL_SECONDS:
            _download_cache.pop(token, None)


def _short_display(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _format_icon(fmt: str) -> str:
    return _DOWNLOAD_FORMAT_ICONS.get((fmt or "").lower(), "📥")


def _short_source(source: Any) -> str:
    raw = str(source or "Web").strip()
    return _DOWNLOAD_SOURCE_SHORT.get(raw, _short_display(raw, 14))


_LANGUAGE_FLAGS = {
    "español": "🇪🇸", "espanol": "🇪🇸",
    "inglés": "🇬🇧", "ingles": "🇬🇧",
    "portugués": "🇵🇹", "portugues": "🇵🇹",
    "italiano": "🇮🇹",
    "francés": "🇫🇷", "frances": "🇫🇷",
    "alemán": "🇩🇪", "aleman": "🇩🇪",
    "rumano": "🇷🇴",
    "esperanto": "🏳️",
    "húngaro": "🇭🇺", "hungaro": "🇭🇺",
    "ruso": "🇷🇺",
    "japonés": "🇯🇵", "japones": "🇯🇵",
    "chino": "🇨🇳",
    "árabe": "🇸🇦", "arabe": "🇸🇦",
    "latín": "🏛️", "latin": "🏛️",
    "neerlandés": "🇳🇱", "neerlandes": "🇳🇱",
    "catalán": "🏴", "catalan": "🏴",
    "griego": "🇬🇷",
    "polaco": "🇵🇱",
    "sueco": "🇸🇪",
    "danés": "🇩🇰", "danes": "🇩🇰",
    "finés": "🇫🇮", "fines": "🇫🇮",
    "noruego": "🇳🇴",
    "checo": "🇨🇿",
    "hebreo": "🇮🇱",
}


def _language_flag(language: Any) -> str:
    value = str(language or "").strip().lower()
    for name, flag in _LANGUAGE_FLAGS.items():
        if value.startswith(name):
            return flag
    return "🌐"


def group_download_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Agrupa variantes de descarga por título + autor normalizados."""
    grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}
    ordered: List[Dict[str, Any]] = []

    for idx, item in enumerate(results):
        title = _short_display(item.get("title") or "Sin título", 160)
        author = _short_display(item.get("author") or "Desconocido", 120)
        key = (
            normalize_genre_slug(title) or title.lower(),
            normalize_genre_slug(author) or author.lower(),
        )

        group = grouped.get(key)
        if group is None:
            group = {
                "title": title,
                "author": author,
                "language": item.get("language"),
                "year": item.get("year"),
                "variants": [],
            }
            grouped[key] = group
            ordered.append(group)
        else:
            if not group.get("language") and item.get("language"):
                group["language"] = item.get("language")
            if not group.get("year") and item.get("year"):
                group["year"] = item.get("year")

        group["variants"].append({"index": idx, "item": item})

    for group in ordered:
        group["variants"].sort(
            key=lambda variant: (
                _DOWNLOAD_FORMAT_ORDER.get(
                    str(variant["item"].get("format") or "").lower(), 9
                ),
                _short_source(variant["item"].get("source")),
            )
        )

    return ordered


def build_download_results_page(
    query: str,
    results: List[Dict[str, Any]],
    token: str,
    page: int = 1,
    per_page: int = _DOWNLOAD_PAGE_SIZE,
) -> Tuple[str, InlineKeyboardMarkup]:
    """Construye el texto y los botones de una página de resultados de /descargar."""
    groups = group_download_results(results)
    total_pages = max(1, (len(groups) + per_page - 1) // per_page)
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    page = max(1, min(page, total_pages))

    start = (page - 1) * per_page
    visible_groups = groups[start: start + per_page]

    lines = [
        "📥 <b>Libros disponibles para descargar</b>",
        f"🔎 <i>\"{html.escape(str(query or ''))}\"</i>",
        (
            f"📚 <b>{len(groups)}</b> obra(s) · <b>{len(results)}</b> archivo(s) · "
            f"Página <b>{page}/{total_pages}</b>"
        ),
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    rows: List[List[InlineKeyboardButton]] = []

    for offset, group in enumerate(visible_groups):
        number = start + offset + 1
        title_safe = html.escape(group["title"])
        author_safe = html.escape(group["author"])

        meta_parts = []
        if group.get("year"):
            meta_parts.append(f"📅 {html.escape(str(group['year']))}")

        lines.append(f"<b>{number}. 📖 {title_safe}</b>")
        lines.append(f"   ✍️ <i>{author_safe}</i>")
        if meta_parts:
            lines.append("   " + " · ".join(meta_parts))

        variant_buttons: List[InlineKeyboardButton] = []
        seen_variant_indexes = set()
        for variant in group["variants"]:
            idx = variant["index"]
            item = variant["item"]
            if idx in seen_variant_indexes:
                continue
            seen_variant_indexes.add(idx)

            fmt = str(item.get("format") or "epub").lower()
            icon = _format_icon(fmt)
            size_safe = html.escape(str(item.get("size_str") or "Directo"))
            source_safe = html.escape(str(item.get("source") or "Web"))
            variant_language = item.get("language")
            language_safe = (
                f" · {_language_flag(variant_language)} {html.escape(str(variant_language))}"
                if variant_language else ""
            )

            lines.append(
                f"   {icon} <b>{fmt.upper()}</b> · {size_safe} · {source_safe}{language_safe}"
            )
            button_language = (
                f" {_language_flag(variant_language)}" if variant_language else ""
            )
            variant_buttons.append(
                InlineKeyboardButton(
                    f"{icon} {fmt.upper()} · {_short_source(item.get('source'))}{button_language}",
                    callback_data=f"dl:{token}:{idx}",
                )
            )

        # Máximo dos botones por fila para que se lean bien en móvil.
        for i in range(0, len(variant_buttons), 2):
            rows.append(variant_buttons[i: i + 2])

        lines.append("")

    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(
                InlineKeyboardButton("⬅️ Anterior", callback_data=f"dlp:{token}:{page - 1}")
            )
        nav_row.append(
            InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data=f"dlp:{token}:{page}")
        )
        if page < total_pages:
            nav_row.append(
                InlineKeyboardButton("Siguiente ➡️", callback_data=f"dlp:{token}:{page + 1}")
            )
        rows.append(nav_row)

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    if total_pages > 1:
        lines.append(
            "👇 <i>Elige el formato que deseas descargar. Usa las flechas para ver más resultados.</i>"
        )
    else:
        lines.append(
            "👇 <i>Elige el formato que deseas descargar y archivar en tu biblioteca.</i>"
        )

    return "\n".join(lines), InlineKeyboardMarkup(rows)


def _download_page_for_index(results: List[Dict[str, Any]], idx: int) -> int:
    """Calcula la página donde aparece una variante dentro de los resultados agrupados."""
    for group_index, group in enumerate(group_download_results(results)):
        if any(variant.get("index") == idx for variant in group.get("variants", [])):
            return group_index // _DOWNLOAD_PAGE_SIZE + 1
    return 1


def _download_back_keyboard(token: str, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Volver a los resultados", callback_data=f"dlp:{token}:{max(1, page)}")]
    ])

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
    import hashlib

    now = time.time()
    _cleanup_download_cache(now)

    try:
        results = await asyncio.wait_for(
            search_external_books(raw_query, max_results=14), timeout=13.0
        )
    except asyncio.TimeoutError:
        logger.warning(f"Timeout de 13s en /descargar para '{raw_query}'")
        results = []
    except Exception as e:
        logger.error(f"Error buscando libros externos: {e}")
        try:
            await status_msg.edit_text(f"❌ Error al consultar los repositorios: {str(e)[:200]}", parse_mode="HTML")
        except Exception:
            pass
        return

    if not results:
        no_res = (
            f"❌ <b>No se encontraron libros para:</b> <i>\"{html.escape(raw_query)}\"</i>\n\n"
            "💡 <b>Consejos de búsqueda:</b>\n"
            "• Busca en español o en inglés, por título o por autor (ej. <code>/descargar El Principito</code> o <code>/descargar Edgar Allan Poe</code>).\n"
            "• Prueba con menos palabras o sólo el apellido del autor (ej. <code>/descargar García Márquez</code>).\n"
            "• También puedes subir tu propio archivo (PDF o EPUB) directamente al chat y Griffin lo clasificará y archivará automáticamente con IA."
        )
        try:
            await status_msg.edit_text(no_res, parse_mode="HTML")
        except Exception:
            pass
        return

    token = hashlib.md5(f"{chat.id}:{raw_query}:{now}".encode()).hexdigest()[:8]
    _download_cache[token] = {
        "results": results,
        "created": now,
        "query": raw_query,
    }

    text, keyboard = build_download_results_page(raw_query, results, token, page=1)
    await status_msg.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


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

    _cleanup_download_cache()
    cached_entry = _download_cache.get(token)
    if not cached_entry:
        await query.edit_message_text("⚠️ <i>Esta solicitud de descarga ha expirado. Usa /descargar nuevamente.</i>", parse_mode="HTML")
        return

    results = cached_entry.get("results") or []
    page = _download_page_for_index(results, idx) if idx >= 0 else 1
    if idx < 0 or idx >= len(results):
        await query.edit_message_text(
            "⚠️ Opción no válida.",
            parse_mode="HTML",
            reply_markup=_download_back_keyboard(token, page),
        )
        return

    chosen_book = results[idx]
    title_safe = html.escape(chosen_book["title"])
    fmt = chosen_book.get("format", "epub").upper()
    await query.edit_message_text(
        f"⏳ <b>[1/3] Descargando:</b> <i>{title_safe}</i> (<code>.{fmt}</code>)...\n"
        f"<i>Conectando al repositorio público y descargando archivo binario...</i>",
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
                parse_mode="HTML",
                reply_markup=_download_back_keyboard(token, page),
            )
            return

        # 2. Notificar avance a análisis de IA y subida a Telegram
        try:
            await query.edit_message_text(
                f"🧠 <b>[2/3] Analizando y archivando:</b> <i>{title_safe}</i>...\n"
                f"<i>Extrayendo metadatos, clasificando con IA y ubicando en su tema...</i>",
                parse_mode="HTML"
            )
        except Exception:
            pass

        # 3. Ingestar en la biblioteca
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
                    parse_mode="HTML",
                    reply_markup=_download_back_keyboard(token, page),
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
            disable_web_page_preview=True,
            reply_markup=_download_back_keyboard(token, page),
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
            disable_web_page_preview=True,
            reply_markup=_download_back_keyboard(token, page),
        )


async def download_page_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Navega entre páginas de resultados de /descargar sin repetir la búsqueda."""
    query = update.callback_query
    if not query or not query.data:
        return

    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "dlp":
        return

    token = parts[1]
    try:
        page = int(parts[2])
    except (TypeError, ValueError):
        return

    _cleanup_download_cache()
    cached_entry = _download_cache.get(token)
    if not cached_entry:
        try:
            await query.answer("⚠️ Solicitud expirada", show_alert=False)
        except Exception:
            pass
        await query.edit_message_text(
            "⚠️ <i>Esta búsqueda ha expirado. Usa /descargar nuevamente.</i>",
            parse_mode="HTML",
        )
        return

    results = cached_entry.get("results") or []
    cached_query = cached_entry.get("query") or ""

    text, keyboard = build_download_results_page(
        cached_query, results, token, page=page
    )
    try:
        await query.answer(f"📄 Página {page}")
    except Exception:
        pass

    try:
        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as edit_err:
        logger.warning(f"No se pudo cambiar la página de descarga: {edit_err}")


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
                text="❌ Este grupo no está vinculado a una biblioteca. Usa /start para ver opciones de vinculación.",
                parse_mode="HTML"
            )
            return

        stmt_topics = select(Topic).where(Topic.telegram_link_id == link.id).order_by(Topic.genre.asc())
        t_res = await session.execute(stmt_topics)
        topics = t_res.scalars().all()

        # Contar libros por tema con aislamiento estricto
        book_filter = (
            or_(Book.telegram_link_id == link.id, Book.user_id == link.user_id)
            if link.chat_type == "private"
            else (Book.telegram_link_id == link.id)
        )
        stmt_books = select(Book).where(book_filter)
        b_res = await session.execute(stmt_books)
        all_books = b_res.scalars().all()

        counts = {}
        for b in all_books:
            counts[b.genre] = counts.get(b.genre, 0) + 1

        if not topics and not all_books:
            empty_msg = (
                "ℹ️ <b>Aún no hay temas registrados en esta biblioteca.</b>\n\n"
                "Sube libros para que Griffin cree automáticamente cada estante por género."
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

        text, keyboard = build_topics_page(chat.id, topic_lines, len(topics) if topics else len(counts), page=1)
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


def build_topics_page(
    chat_id: int,
    topic_lines: List[str],
    total_topics: int,
    page: int = 1,
    per_page: int = 10
) -> tuple[str, InlineKeyboardMarkup]:
    """Genera la página del catálogo de temas con paginación interactiva."""
    total_pages = max(1, (len(topic_lines) + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_items = topic_lines[start_idx:end_idx]

    lines = [
        "🏷️ <b>Temas y Géneros Disponibles</b>",
        f"<i>(Página {page} de {total_pages} — {total_topics} estantes registrados)</i>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    ]
    lines.extend(page_items)
    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Pulsa sobre cualquier tema para entrar directamente a él.</i>")

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"topics:page:{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="topics:noop"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"topics:page:{page + 1}"))

    keyboard = InlineKeyboardMarkup([nav_buttons]) if total_pages > 1 else InlineKeyboardMarkup([[]])
    return "\n".join(lines), keyboard


async def topics_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paginación interactiva de la lista de temas sin reenviar mensajes."""
    query = update.callback_query
    if not query or not query.data:
        return
    try:
        await query.answer()
    except Exception:
        pass
    if query.data == "topics:noop":
        return
    if not query.data.startswith("topics:page:"):
        return

    page_num = int(query.data.split(":")[-1])
    chat = update.effective_chat
    if not chat:
        return

    import html
    from app.services.ai_classifier import get_genre_emoji

    async with AsyncSessionLocal() as session:
        link = await _get_or_create_link(context.bot, session, chat.id)
        if not link:
            return

        stmt_topics = select(Topic).where(Topic.telegram_link_id == link.id).order_by(Topic.genre.asc())
        t_res = await session.execute(stmt_topics)
        topics = t_res.scalars().all()

        stmt_books = select(Book).where(Book.telegram_link_id == link.id)

        b_res = await session.execute(stmt_books)
        all_books = b_res.scalars().all()

        counts = {}
        for b in all_books:
            counts[b.genre] = counts.get(b.genre, 0) + 1

        clean_chat_id = str(chat.id).replace("-100", "").replace("-", "")
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

        text, keyboard = build_topics_page(chat.id, topic_lines, len(topics) if topics else len(counts), page=page_num)
        try:
            await query.edit_message_text(
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception as edit_err:
            logger.error(f"Error editando lista de temas página {page_num}: {edit_err}")


def build_topic_index_page(
    chat_id: int,
    thread_id: int,
    genre_name: str,
    books: List[Book],
    page: int = 1,
    per_page: int = 10
) -> tuple[str, InlineKeyboardMarkup]:
    """Genera el texto y la botonera de paginación del índice de un tema para no saturar el grupo."""
    import html
    from app.services.ai_classifier import get_genre_emoji

    total_books = len(books)
    total_pages = max(1, (total_books + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_books = books[start_idx:end_idx]

    emo = get_genre_emoji(genre_name)
    lines = [
        f"📌 <b>ÍNDICE DE LA COLECCIÓN: {emo} {html.escape(genre_name)}</b>",
        f"<i>(Página {page} de {total_pages} — {total_books} obras disponibles)</i>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    ]

    clean_chat_id = str(chat_id).replace("-100", "").replace("-", "")

    for i, b in enumerate(page_books, start=start_idx + 1):
        fmt = (b.file_format or "pdf").upper()
        book_chat = chat_id
        if getattr(b, "telegram_link", None) and getattr(b.telegram_link, "chat_id", None):
            book_chat = b.telegram_link.chat_id
        b_clean = str(book_chat).replace("-100", "").replace("-", "")
        msg_link = f"https://t.me/c/{b_clean}/{b.telegram_message_id}" if b.telegram_message_id and str(book_chat).startswith("-100") else None
        link_html = f'<a href="{msg_link}">👉 Ver libro</a>' if msg_link else ""
        title_safe = html.escape(b.title or "Sin título")
        author_safe = html.escape(b.author or "Desconocido")
        pub_yr = f" ({b.publication_year})" if b.publication_year and b.publication_year != "Desconocido" else ""
        lines.append(f"<b>{i}.</b> 📖 <b>{title_safe}</b>{pub_yr} — <i>{author_safe}</i> (<code>.{fmt}</code>) {link_html}")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Navega con los botones para ver toda la colección sin saturar el grupo.</i>")

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"tindex:p:{thread_id}:{page - 1}"))
    nav_buttons.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="tindex:noop"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"tindex:p:{thread_id}:{page + 1}"))

    keyboard = InlineKeyboardMarkup([nav_buttons]) if total_pages > 1 else InlineKeyboardMarkup([[]])
    return "\n".join(lines), keyboard


async def topic_index_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la paginación del índice de un tema mediante edición del mensaje original."""
    query = update.callback_query
    if not query or not query.data:
        return
    try:
        await query.answer()
    except Exception:
        pass

    if query.data == "tindex:noop":
        return

    parts = query.data.split(":")
    if len(parts) >= 4 and parts[1] == "p":
        thread_id = int(parts[2])
        page_num = int(parts[3])
        chat = update.effective_chat
        if not chat:
            return

        async with AsyncSessionLocal() as session:
            link = await _get_or_create_link(context.bot, session, chat.id)
            if not link:
                return

            stmt_topic = select(Topic).where(
                Topic.telegram_link_id == link.id,
                Topic.topic_id == thread_id
            )
            t_res = await session.execute(stmt_topic)
            topic = t_res.scalar_one_or_none()
            genre_name = topic.genre if topic else "General"

            stmt_books = (
                select(Book)
                .options(selectinload(Book.telegram_link))
                .where(Book.telegram_link_id == link.id, Book.genre == genre_name)
                .order_by(Book.title.asc())
            )
            b_res = await session.execute(stmt_books)
            books = b_res.scalars().all()

            text, keyboard = build_topic_index_page(chat.id, thread_id, genre_name, books, page=page_num)
            try:
                await query.edit_message_text(
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            except Exception as e:
                logger.error(f"Error editando página de índice {page_num}: {e}")


async def topic_index_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /indice:
    Debe ejecutarse DENTRO de un tema. Publica un mensaje índice paginado interactivamente
    con los libros disponibles en este tema específico, con enlaces directos para navegar sin saturar el chat.
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
                text="❌ Este grupo no está vinculado a una biblioteca. Usa /start para ver opciones de vinculación.",
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

        if not books:
            empty_index = (
                f"📌 <b>ÍNDICE DE LA COLECCIÓN: {emo} {html.escape(genre_name)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<i>(Aún no hay libros archivados en este tema)</i>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )
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

        text, keyboard = build_topic_index_page(chat.id, thread_id, genre_name, books, page=1)
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
                    await status_msg.edit_text("❌ Este grupo no está vinculado a una biblioteca.", parse_mode="HTML")
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
                await message.reply_text("❌ Este grupo no está vinculado a una biblioteca.", parse_mode="HTML")
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
        f"<i>El catálogo de la biblioteca se ha actualizado con la información correcta.</i>",
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
            text="🔄 <i>Verificando y sincronizando estantes de la biblioteca con Telegram...</i>",
            parse_mode="HTML"
        )
    except Exception:
        pass

    from app.services.book_sync_service import sync_all_library_for_chat, reorganize_misplaced_books

    async with AsyncSessionLocal() as session:
        link = await _get_or_create_link(context.bot, session, chat.id)
        if not link:
            err_text = "❌ Este grupo aún no está vinculado a una biblioteca."
            if status_msg:
                await status_msg.edit_text(err_text, parse_mode="HTML")
            else:
                await context.bot.send_message(chat_id=chat.id, message_thread_id=thread_id, text=err_text, parse_mode="HTML")
            return

        sync_result = await sync_all_library_for_chat(context.bot, session, link.id, chat.id)
        reorg_result = {}
        if link.forum_enabled:
            reorg_result = await reorganize_misplaced_books(
                bot=context.bot,
                session=session,
                link=link,
                chat_id=chat.id,
                force=False,
                threshold=10
            )

    purged = sync_result.get("purged_books", 0)
    duplicates = sync_result.get("duplicates_removed", 0)
    active = sync_result.get("active_books", 0)
    topics = sync_result.get("active_topics", 0)
    reorg_moved = reorg_result.get("moved_count", 0)

    reorg_line = f"📦 <b>Libros fuera de tema reubicados:</b> <code>{reorg_moved}</code>\n" if reorg_moved > 0 else ""

    clean_text = (
        "🧹 <b>Sincronización y Mantenimiento Completados</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <b>Libros extraviados detectados:</b> <code>{purged}</code>\n"
        f"🗑️ <b>Copias duplicadas eliminadas:</b> <code>{duplicates}</code>\n"
        f"{reorg_line}"
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
            err_text = "❌ Este grupo no está vinculado a una biblioteca."
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
                text="❌ Este grupo no está vinculado a una biblioteca. Usa /start para ver opciones de vinculación.",
                parse_mode="HTML"
            )
            return

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
                InlineKeyboardButton("📖 Leyendo", callback_data=f"rs:reading:{target_book.id}"),
                InlineKeyboardButton("✅ Leído", callback_data=f"rs:finished:{target_book.id}"),
            ],
            [
                InlineKeyboardButton("⭐ Favorito", callback_data=f"rs:fav:{target_book.id}"),
                InlineKeyboardButton("📊 Progreso", callback_data=f"rs:prog:{target_book.id}"),
            ],
            [
                InlineKeyboardButton("🤝 Lectura Conjunta", callback_data=f"br:start:{target_book.id}"),
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
        "🤖 <b>Guía Oficial de Comandos de Griffin:</b>\n\n"
        "📚 <b>Exploración & Catálogo:</b>\n"
        "• <code>/buscar &lt;término&gt;</code> — Encuentra libros por título, autor o saga.\n"
        "• <code>/libros</code> — Explora el catálogo interactivo de la biblioteca.\n"
        "• <code>/temas</code> — Lista de géneros y estantes con conteo de obras.\n"
        "• <code>/indice</code> — <i>(Dentro de un tema)</i> Publica el índice interactivo de ese género.\n"
        "• <code>/info &lt;libro&gt;</code> — Ficha completa con botones de lectura y co-lectores.\n"
        "• <code>/descargar &lt;título&gt;</code> — Busca y descarga libros de repositorios abiertos (Internet Archive, Gutenberg).\n\n"
        "👥 <b>Club de Lectura & Progreso:</b>\n"
        "• <code>/leerjuntos &lt;libro&gt;</code> — Inicia o únete a una lectura conjunta con tus compañeros.\n"
        "• <code>/mislibros</code> — Tu perfil de lector: libros terminados, lecturas activas, avance y co-lectores.\n"
        "• <code>/progreso &lt;porcentaje&gt;</code> — Actualiza tu porcentaje de lectura en curso (ej. <code>/progreso 45%</code>).\n\n"
        "⚙️ <b>Gestión & Mantenimiento:</b>\n"
        "• <code>/registrar</code> — Responde a cualquier libro antiguo para indexarlo y clasificarlo con IA.\n"
        "• <code>/reorganizar</code> — Mueve automáticamente libros fuera de tema a su estante correspondiente.\n"
        "• <code>/deduplicar</code> — Detecta y elimina copias duplicadas de la biblioteca.\n"
        "• <code>/sincronizar</code> — Mantenimiento integral, depuración y verificación de estantes.\n"
        "• <code>/start</code> — Menú inicial para biblioteca personal o vincular grupo.\n"
        "• <code>/help</code> — Muestra este menú de ayuda.\n\n"
        "✨ <b>Modo Cero Fricción:</b> No necesitas comandos para subir libros nuevos: ¡simplemente envía o reenvía cualquier archivo PDF o EPUB al chat y Griffin se encarga de clasificarlo y archivarlo solo!"
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
                bot_me = await context.bot.get_me()
                unlinked_text = (
                    "👋 <b>¡Hola a todos! Soy Griffin, tu bibliotecario inteligente de LibroSync.</b>\n\n"
                    "📚 <b>Para activar y vincular la biblioteca de este grupo:</b>\n"
                    f"1. Abre el chat privado con @{bot_me.username}.\n"
                    "2. Envía <code>/start</code> y selecciona <b>'👥 Biblioteca de Grupo'</b>.\n"
                    "3. Elige la vigencia del código y usa el botón para añadir el bot o escribe aquí: <code>/start &lt;CODIGO&gt;</code>\n\n"
                    "💡 <i>Asegúrate de activar <b>Temas/Topics</b> en este grupo y otorgarme permiso de <b>'Administrar temas'</b> para organizar los libros por género automáticamente.</i>"
                )
                try:
                    await context.bot.send_message(chat_id=chat.id, text=unlinked_text, parse_mode="HTML")
                except Exception as e:
                    logger.debug(f"No se pudo enviar mensaje de bienvenida a grupo no vinculado: {e}")
                return

            link.chat_title = status_info["chat_title"]
            link.bot_is_admin = status_info["bot_is_admin"]
            link.forum_enabled = status_info["forum_enabled"]
            await session.commit()

            welcome_text = (
                "👋 <b>¡Hola a todos! Soy Griffin, el bibliotecario inteligente de LibroSync.</b>\n\n"
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
            await message.reply_text("❌ Este chat no está vinculado a una biblioteca.", parse_mode="HTML")
            return

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
                    "📖 <b>Lecturas Conjuntas:</b>\n\n"
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

        # Consultar lecturas conjuntas activas y sus co-lectores
        stmt_br = (
            select(BuddyRead)
            .join(BuddyReadMember, BuddyReadMember.buddy_read_id == BuddyRead.id)
            .options(
                selectinload(BuddyRead.book),
                selectinload(BuddyRead.members).selectinload(BuddyReadMember.user)
            )
            .where(
                BuddyReadMember.user_id == user_db.id,
                BuddyRead.status == "active"
            )
        )
        br_res = await session.execute(stmt_br)
        active_buddy_reads = br_res.scalars().all()

    u_name = html.escape(user_tg.first_name or user_tg.username or "Lector")
    lines = [
        f"📚 <b>Estantes de Lectura de {u_name}</b>",
        f"<i>(Total en seguimiento: {shelves['total_tracked']} obras)</i>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    ]

    # 1. Libros leídos y cuáles
    finished = shelves["finished"]
    lines.append(f"🏆 <b>Libros Leídos / Terminados ({len(finished)}):</b>")
    if finished:
        for fin in finished[:15]:
            fin_title = html.escape(fin.book.title if fin.book else "Libro")
            fin_auth = html.escape(fin.book.author if (fin.book and fin.book.author) else "")
            auth_str = f" — <i>{fin_auth}</i>" if fin_auth else ""
            lines.append(f"• ✅ <b>{fin_title}</b>{auth_str}")
        if len(finished) > 15:
            lines.append(f"  <i>... y {len(finished) - 15} libros más</i>")
    else:
        lines.append("<i>(Aún no has marcado libros terminados)</i>")
    lines.append("")

    # 2. Leyendo actualmente y su progreso
    reading = shelves["reading"]
    lines.append(f"📖 <b>Leyendo Actualmente ({len(reading)}):</b>")
    if reading:
        for r in reading:
            b_title = html.escape(r.book.title if r.book else "Libro")
            b_auth = html.escape(r.book.author if r.book else "Desconocido")
            pct = r.progress_percent or 0.0
            bar = format_progress_bar(pct, length=8)
            lines.append(f"• <b>{b_title}</b> — <i>{b_auth}</i>\n  Avance: {bar} (<b>{pct:.0f}%</b>)")
    else:
        lines.append("<i>(No tienes libros en curso actualmente)</i>")
    lines.append("")

    # 3. Lectura en conjunto y con quién
    lines.append(f"🤝 <b>Lecturas Conjuntas Activas ({len(active_buddy_reads)}):</b>")
    if active_buddy_reads:
        for br in active_buddy_reads:
            b_title = html.escape(br.book.title if br.book else "Libro")
            co_members = [
                html.escape(m.user.display_name or m.user.username or f"Lector {m.user_id}")
                for m in br.members if m.user_id != user_db.id
            ]
            if co_members:
                with_str = f"Leyendo con: <b>{', '.join(co_members[:4])}</b>"
                if len(co_members) > 4:
                    with_str += f" (+{len(co_members) - 4} más)"
            else:
                with_str = "<i>(Esperando co-lectores)</i>"

            my_m = next((m for m in br.members if m.user_id == user_db.id), None)
            my_pct = my_m.progress_percent if my_m else 0.0
            my_bar = format_progress_bar(my_pct, length=8)
            lines.append(f"• <b>{b_title}</b>\n  👥 {with_str}\n  Tu avance: {my_bar} (<b>{my_pct:.0f}%</b>)")
    else:
        lines.append("<i>(No estás participando en ninguna lectura conjunta activa)</i>")
    lines.append("")

    # 4. Favoritos
    favs = shelves["favorites"]
    lines.append(f"⭐ <b>Mis Favoritos ({len(favs)}):</b>")
    if favs:
        for f in favs[:8]:
            f_title = html.escape(f.book.title if f.book else "Libro")
            lines.append(f"• ⭐ <b>{f_title}</b>")
        if len(favs) > 8:
            lines.append(f"  <i>... y {len(favs) - 8} más</i>")
    else:
        lines.append("<i>(Aún no has marcado libros favoritos)</i>")
    lines.append("")

    # 5. Por leer
    to_read = shelves["to_read"]
    lines.append(f"📌 <b>Por Leer / Deseos ({len(to_read)}):</b>")
    if to_read:
        for tr in to_read[:8]:
            tr_title = html.escape(tr.book.title if tr.book else "Libro")
            lines.append(f"• 🔖 <b>{tr_title}</b>")
        if len(to_read) > 8:
            lines.append(f"  <i>... y {len(to_read) - 8} más</i>")
    else:
        lines.append("<i>(Tu lista de deseos está vacía)</i>")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Inicia una lectura conjunta con /leerjuntos o actualiza tu avance con /progreso.</i>")

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
    """Maneja acciones sobre el estante personal: favorito, en curso, finalizado, progreso."""
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

        elif action == "reading":
            await update_user_book_state(session, user_db.id, book_id, status="reading")
            await query.answer("📖 Marcado como: Leyendo Actualmente")

        elif action == "finished":
            await update_user_book_state(session, user_db.id, book_id, status="finished", progress_percent=100.0)
            await query.answer("🏆 ¡Felicitaciones! Libro marcado como Terminado (100%)")

        elif action == "prog":
            prog_kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("25%", callback_data=f"rs:setp:{book_id}:25"),
                    InlineKeyboardButton("50%", callback_data=f"rs:setp:{book_id}:50"),
                    InlineKeyboardButton("75%", callback_data=f"rs:setp:{book_id}:75"),
                    InlineKeyboardButton("100%", callback_data=f"rs:setp:{book_id}:100"),
                ],
                [
                    InlineKeyboardButton("🔙 Volver", callback_data=f"rs:back:{book_id}")
                ]
            ])
            try:
                await query.edit_message_reply_markup(reply_markup=prog_kb)
            except Exception:
                pass
            await query.answer("Selecciona tu avance de lectura:")

        elif action == "setp":
            pct = float(parts[3])
            new_st = "finished" if pct >= 100.0 else "reading"
            await update_user_book_state(session, user_db.id, book_id, status=new_st, progress_percent=pct)
            await query.answer(f"📊 Progreso actualizado al {pct:.0f}%")

        elif action == "back":
            back_kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📖 Leyendo", callback_data=f"rs:reading:{book_id}"),
                    InlineKeyboardButton("✅ Leído", callback_data=f"rs:finished:{book_id}"),
                ],
                [
                    InlineKeyboardButton("⭐ Favorito", callback_data=f"rs:fav:{book_id}"),
                    InlineKeyboardButton("📊 Progreso", callback_data=f"rs:prog:{book_id}"),
                ],
                [
                    InlineKeyboardButton("🤝 Lectura Conjunta", callback_data=f"br:start:{book_id}"),
                ]
            ])
            try:
                await query.edit_message_reply_markup(reply_markup=back_kb)
            except Exception:
                pass
            await query.answer()


async def reorganize_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Comando /reorganizar o /organizar:
    Detecta automáticamente libros que no están en su tema o que están en General,
    crea los temas faltantes y los mueve a su tema correspondiente de forma autónoma.
    """
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    from app.services.book_sync_service import reorganize_misplaced_books

    status_msg = await message.reply_text(
        "🔍 <i>Escaneando biblioteca para detectar libros fuera de tema...</i>",
        parse_mode="HTML"
    )

    async with AsyncSessionLocal() as session:
        link = await _get_or_create_link(context.bot, session, chat.id)
        if not link:
            await status_msg.edit_text("❌ Este grupo no está vinculado a una biblioteca.", parse_mode="HTML")
            return

        if not link.forum_enabled:
            await status_msg.edit_text(
                "ℹ️ Este grupo no tiene temas/topics habilitados. Activa los temas en el grupo para organizar por géneros.",
                parse_mode="HTML"
            )
            return

        res = await reorganize_misplaced_books(
            bot=context.bot,
            session=session,
            link=link,
            chat_id=chat.id,
            force=True,
            current_thread_id=getattr(message, "message_thread_id", None)
        )

    moved = res.get("moved_count", 0)
    misplaced = res.get("misplaced_count", 0)
    reclassified = res.get("reclassified_count", 0)
    remaining = res.get("remaining_count", 0)

    if misplaced == 0:
        await status_msg.edit_text(
            "✨ <b>¡Biblioteca perfectamente organizada!</b>\nTodos los libros se encuentran en sus temas correspondientes.",
            parse_mode="HTML"
        )
    else:
        reclass_msg = f"• <b>Re-clasificados con IA:</b> <code>{reclassified}</code>\n" if reclassified > 0 else ""
        rem_msg = f"• <b>Libros restantes por procesar:</b> <code>{remaining}</code>\n" if remaining > 0 else ""
        await status_msg.edit_text(
            f"📦 <b>Reorganización Completada:</b>\n\n"
            f"• <b>Libros detectados en este tema:</b> <code>{misplaced}</code>\n"
            f"• <b>Libros movidos a sus estantes:</b> <code>{moved}</code>\n"
            f"{reclass_msg}"
            f"{rem_msg}\n"
            "🏷️ <i>Los libros han sido archivados en sus estantes temáticos.</i>\n\n"
            "💡 <i>Nota: Si el mensaje original fue publicado por el creador del grupo, la API de Telegram no permite borrarlo; se creó la copia en su tema correspondiente.</i>",
            parse_mode="HTML"
        )



