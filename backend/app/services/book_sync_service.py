import asyncio
import html
import logging
from collections import defaultdict
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import BadRequest, TelegramError
from app.models.book import Book
from app.models.topic import Topic
from app.models.telegram_link import TelegramLink
from app.models.reading import ReadingState, BuddyRead
from app.services.topic_resolver import normalize_genre_slug

logger = logging.getLogger(__name__)

async def check_telegram_message_exists(bot: Bot, chat_id: int, message_id: int) -> bool:
    """
    Comprueba de forma no destructiva si un mensaje existe en el chat de Telegram.
    Intenta editar el reply_markup (sin botones). Si Telegram responde:
    - 'Message to edit not found', 'message not found', 'invalid': el mensaje FUE ELIMINADO.
    - 'Message can't be edited', 'message is not modified', o éxito: el mensaje EXISTE.
    - Error de red o timeout: se asume True por seguridad para evitar falsos positivos.
    """
    if not message_id or not chat_id:
        return False

    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
        return True
    except BadRequest as e:
        err = str(e).lower()
        if any(needle in err for needle in ["not found", "message to edit not found", "message_id_invalid", "chat not found"]):
            return False
        # Cualquier otro BadRequest (ej: "Message can't be edited", "Message is not modified") confirma que el mensaje EXISTE
        return True
    except Exception as e:
        logger.warning(f"Error verificando mensaje {message_id} en chat {chat_id}: {e}")
        return True


async def deduplicate_library_for_chat(
    bot: Bot,
    session: AsyncSession,
    link_id: int,
    chat_id: int
) -> Dict[str, Any]:
    """
    Escanea la biblioteca de un grupo y elimina libros duplicados de forma autónoma:
    1. Agrupa los libros por título normalizado y formato.
    2. Identifica la versión canónica (priorizando la que tenga mensaje activo en Telegram o género específico).
    3. Para las versiones duplicadas secundarias:
       - Si Griffin tiene permisos de admin y el mensaje existe, elimina el mensaje de Telegram.
       - Reasigna de forma segura cualquier estado de lectura (ReadingState) o lectura conjunta (BuddyRead).
       - Elimina el registro secundario de la base de datos.
    """
    stmt = select(Book).where(Book.telegram_link_id == link_id)
    res = await session.execute(stmt)
    all_books = res.scalars().all()

    if not all_books:
        return {"duplicates_removed": 0, "details": []}

    stmt_link = select(TelegramLink).where(TelegramLink.id == link_id)
    link = (await session.execute(stmt_link)).scalar_one_or_none()
    can_delete_telegram = bool(link and link.bot_is_admin)

    groups = defaultdict(list)
    for b in all_books:
        t_slug = normalize_genre_slug(b.title or "")
        fmt = (b.file_format or "epub").lower()
        groups[(t_slug, fmt)].append(b)

    removed_details: List[Dict[str, Any]] = []

    for key, book_list in groups.items():
        if len(book_list) <= 1:
            continue

        # Ordenar para elegir versión canónica:
        sorted_books = sorted(
            book_list,
            key=lambda b: (
                1 if b.telegram_message_id else 0,
                1 if b.genre and b.genre.lower() != "general" else 0,
                b.reading_progress or 0.0,
                -b.id
            ),
            reverse=True
        )

        canonical = sorted_books[0]
        duplicates = sorted_books[1:]

        for dup in duplicates:
            # 1. Borrar mensaje duplicado en Telegram si existe y el bot es admin
            if dup.telegram_message_id and can_delete_telegram:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=dup.telegram_message_id)
                except Exception as del_err:
                    logger.debug(f"No se pudo eliminar mensaje duplicado {dup.telegram_message_id}: {del_err}")

            # 2. Reasignar ReadingStates de forma segura
            rs_stmt = select(ReadingState).where(ReadingState.book_id == dup.id)
            rs_list = (await session.execute(rs_stmt)).scalars().all()
            for rs in rs_list:
                c_rs_stmt = select(ReadingState).where(
                    ReadingState.book_id == canonical.id,
                    ReadingState.user_id == rs.user_id
                )
                c_rs = (await session.execute(c_rs_stmt)).scalar_one_or_none()
                if c_rs:
                    if (rs.progress_percent or 0) > (c_rs.progress_percent or 0):
                        c_rs.progress_percent = rs.progress_percent
                        c_rs.current_page = rs.current_page
                    await session.delete(rs)
                else:
                    rs.book_id = canonical.id

            # 3. Reasignar BuddyReads de forma segura
            br_stmt = select(BuddyRead).where(BuddyRead.book_id == dup.id)
            br_list = (await session.execute(br_stmt)).scalars().all()
            for br in br_list:
                c_br_stmt = select(BuddyRead).where(
                    BuddyRead.book_id == canonical.id,
                    BuddyRead.status == "active"
                )
                c_br = (await session.execute(c_br_stmt)).scalar_one_or_none()
                if c_br:
                    for m in br.members:
                        m.buddy_read_id = c_br.id
                    await session.delete(br)
                else:
                    br.book_id = canonical.id

            removed_details.append({
                "id": dup.id,
                "title": dup.title,
                "author": dup.author,
                "format": dup.file_format or "epub"
            })
            await session.delete(dup)

    if removed_details:
        await session.commit()

    return {
        "duplicates_removed": len(removed_details),
        "details": removed_details
    }


async def purge_deleted_books_for_chat(
    bot: Bot,
    session: AsyncSession,
    link_id: int,
    chat_id: int,
    notify_lost: bool = False
) -> int:
    """
    Verifica todos los libros registrados para este grupo en la BD y detecta
    aquellos cuyos mensajes hayan sido eliminados en Telegram (por borrado manual o cuenta eliminada).
    - Si notify_lost es True y bot tiene send_message:
      Emite una alerta interactiva con botones [Recuperar y Descargar] y [Descartar libro]
      en el tema correspondiente, y conserva el registro en BD desvinculando telegram_message_id.
    - Si notify_lost es False:
      Purga directamente el registro de la base de datos.
    """
    stmt = select(Book).where(Book.telegram_link_id == link_id)
    res = await session.execute(stmt)
    all_books = res.scalars().all()

    if not all_books:
        return 0

    sem = asyncio.Semaphore(10)
    dead_book_ids: List[int] = []

    async def verify_book(book: Book):
        if not book.telegram_message_id:
            return
        async with sem:
            is_alive = await check_telegram_message_exists(bot, chat_id, book.telegram_message_id)
            if not is_alive:
                dead_book_ids.append(book.id)

    await asyncio.gather(*(verify_book(b) for b in all_books))

    if dead_book_ids:
        logger.info(f"Detectados {len(dead_book_ids)} libros eliminados en Telegram (IDs: {dead_book_ids})...")
        for b in all_books:
            if b.id in dead_book_ids:
                if notify_lost and hasattr(bot, "send_message"):
                    # Localizar tema del libro si existe
                    stmt_t = select(Topic).where(Topic.telegram_link_id == link_id, Topic.genre == b.genre)
                    t_res = await session.execute(stmt_t)
                    topic = t_res.scalar_one_or_none()
                    target_thread_id = topic.topic_id if topic else None

                    rec_kb = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("📥 Recuperar y Descargar", callback_data=f"rec:get:{b.id}"),
                            InlineKeyboardButton("🗑️ Descartar libro", callback_data=f"rec:del:{b.id}")
                        ]
                    ])
                    t_safe = html.escape(b.title or "Sin título")
                    a_safe = html.escape(b.author or "Desconocido")
                    g_safe = html.escape(b.genre or "General")
                    fmt_safe = (b.file_format or "epub").upper()

                    alert_text = (
                        "⚠️ <b>¡Alerta de Biblioteca: Libro Extraviado!</b>\n\n"
                        "El archivo del siguiente libro ya no está disponible en Telegram (mensaje eliminado o cuenta borrada):\n"
                        f"📖 <b>{t_safe}</b>\n"
                        f"✍️ <i>{a_safe}</i>\n"
                        f"🏷️ Estante: <b>{g_safe}</b> (<code>.{fmt_safe}</code>)\n\n"
                        "<i>¿Deseas que busque y descargue una copia de reemplazo para restaurarlo automáticamente en este tema?</i>"
                    )
                    try:
                        await bot.send_message(
                            chat_id=chat_id,
                            message_thread_id=target_thread_id,
                            text=alert_text,
                            reply_markup=rec_kb,
                            parse_mode="HTML"
                        )
                    except Exception as ex:
                        logger.warning(f"No se pudo enviar alerta de libro perdido {b.id}: {ex}")

                    # Desvincular message_id para indicar que requiere restauración y evitar re-alertas
                    b.telegram_message_id = None
                else:
                    await session.delete(b)
        await session.commit()

    return len(dead_book_ids)


async def sync_all_library_for_chat(
    bot: Bot,
    session: AsyncSession,
    link_id: int,
    chat_id: int,
    notify_lost: bool = False
) -> Dict[str, Any]:
    """
    Sincronización integral rápida:
    1. Deduplica automáticamente copias duplicadas de libros en la BD.
    2. Cuenta libros activos y estantes sincronizados.
    3. Devuelve métricas actualizadas sin generar cuellos de botella en la Bot API.
    """
    # 1. Deduplicación en base de datos
    dedup_res = await deduplicate_library_for_chat(bot, session, link_id, chat_id)
    duplicates_removed = dedup_res.get("duplicates_removed", 0)

    # 2. Contar libros activos
    stmt_books = select(Book).where(Book.telegram_link_id == link_id)
    b_res = await session.execute(stmt_books)
    active_books = len(b_res.scalars().all())

    # 3. Contar temas / estantes
    stmt_topics = select(Topic).where(Topic.telegram_link_id == link_id)
    t_res = await session.execute(stmt_topics)
    topics = t_res.scalars().all()
    active_topics_count = len(topics)

    await session.commit()

    return {
        "status": "ok",
        "purged_books": 0,
        "duplicates_removed": duplicates_removed,
        "active_books": active_books,
        "active_topics": active_topics_count,
        "message": f"Sincronización exitosa: {active_books} libros en {active_topics_count} estantes."
    }

