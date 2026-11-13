import asyncio
import logging
import re
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from telegram import Bot, Message

from app.models.book import Book
from app.models.topic import Topic
from app.models.telegram_link import TelegramLink
from app.services.ai_classifier import classify_book_with_gemini, get_genre_emoji
from app.services.telegram_service import move_or_repost_to_topic, ThreadNotFoundError
from app.services.topic_resolver import resolve_or_create_topic, delete_topic_by_thread_id
from app.services.book_identity import book_identity_key

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = [".pdf", ".epub", ".mobi"]
_chat_locks: Dict[int, asyncio.Lock] = {}

def get_chat_lock(chat_id: int) -> asyncio.Lock:
    """Retorna un lock exclusivo por chat para serializar el procesamiento masivo y evitar bloqueos en SQLite."""
    if chat_id not in _chat_locks:
        _chat_locks[chat_id] = asyncio.Lock()
    return _chat_locks[chat_id]

def clean_filename(filename: str) -> tuple[str, str]:
    if "." in filename:
        base, ext = filename.rsplit(".", 1)
        return base, ext.lower()
    return filename, "pdf"

async def process_book_message(
    bot: Bot,
    session: AsyncSession,
    link: TelegramLink,
    chat_id: int,
    message: Message,
    delete_original: bool = True,
    caption_override: Optional[str] = None
) -> Dict[str, Any]:
    """
    Procesa un archivo de libro individual de principio a fin:
    1. Comprueba extensión y deduplicación binaria/semántica.
    2. Clasifica metadata con Gemini AI (título, autor, género, emoji).
    3. Resuelve o auto-crea el Topic correspondiente en Telegram.
    4. Mueve/copia el archivo a su estante temático.
    5. Guarda el registro en la base de datos.
    """
    doc = message.document
    if not doc:
        return {"status": "error", "error": "El mensaje no contiene documento."}

    filename = doc.file_name or "libro_desconocido"
    base_raw, ext = clean_filename(filename)

    if f".{ext}" not in SUPPORTED_EXTENSIONS:
        return {"status": "ignored", "error": f"Extensión .{ext} no soportada."}

    # 1. Deduplicación por file_unique_id
    file_unique_id = getattr(doc, "file_unique_id", None)
    clean_chat_id = str(chat_id).replace("-100", "").replace("-", "")

    if file_unique_id:
        stmt_dup = select(Book).where(
            Book.telegram_link_id == link.id,
            Book.file_unique_id == file_unique_id
        )
        dup_res = await session.execute(stmt_dup)
        existing_book = dup_res.scalar_one_or_none()
        if existing_book and existing_book.telegram_message_id:
            if delete_original and link.bot_is_admin:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
                except Exception:
                    pass
            msg_link = f"https://t.me/c/{clean_chat_id}/{existing_book.telegram_message_id}"
            return {
                "status": "duplicate",
                "title": existing_book.title,
                "author": existing_book.author,
                "genre": existing_book.genre,
                "dest_link": msg_link,
                "file_format": existing_book.file_format
            }

    # 2. Contexto del thread actual y géneros existentes
    current_thread_id = getattr(message, "message_thread_id", None)
    current_topic_hint = None
    if current_thread_id:
        stmt_cur = select(Topic).where(
            Topic.telegram_link_id == link.id,
            Topic.topic_id == current_thread_id
        )
        cur_res = await session.execute(stmt_cur)
        cur_obj = cur_res.scalar_one_or_none()
        if cur_obj:
            current_topic_hint = cur_obj.genre

    stmt_topics = select(Topic).where(Topic.telegram_link_id == link.id)
    t_res = await session.execute(stmt_topics)
    existing_topics_list = [t.genre for t in t_res.scalars().all()]

    # 3. Inspección profunda de metadatos internos si el nombre es genérico o críptico
    from app.services.metadata_extractor import is_generic_or_cryptic_filename, extract_internal_book_metadata
    from app.services.telegram_service import get_telegram_file_bytes

    internal_meta = None
    if is_generic_or_cryptic_filename(filename) and doc.file_id:
        file_size_mb = (getattr(doc, "file_size", 0) or 0) / (1024 * 1024)
        if file_size_mb <= 35:
            logger.info(f"Nombre ambiguo o genérico detectado ('{filename}'). Inspeccionando contenido interno del libro...")
            try:
                file_bytes, _ = await get_telegram_file_bytes(bot, doc.file_id)
                internal_meta = extract_internal_book_metadata(file_bytes, ext)
                logger.info(f"Metadatos internos extraídos para '{filename}': {internal_meta}")
            except Exception as ex:
                logger.warning(f"No se pudo inspeccionar el interior del archivo '{filename}': {ex}")

    # 4. Clasificación con IA
    effective_caption = caption_override if caption_override is not None else message.caption
    classification = await classify_book_with_gemini(
        filename=filename,
        caption=effective_caption,
        existing_topics=existing_topics_list,
        current_topic_hint=current_topic_hint,
        internal_metadata=internal_meta
    )

    title = classification.get("title", base_raw)
    author = classification.get("author", "Desconocido")
    genre = classification.get("genre", "General")
    suggested_emoji = classification.get("emoji", "📖")
    pub_year = classification.get("publication_year") or "Desconocido"

    # Garantizar preservación de capítulos para Manga/Manhwa/Manhua
    from app.services.ai_classifier import extract_manga_chapter_info, format_manga_title
    chap_info = extract_manga_chapter_info(filename) or (extract_manga_chapter_info(effective_caption) if effective_caption else None)
    if chap_info:
        title = format_manga_title(title, filename)
        if genre == "General":
            genre = "Manga/Manhwa/Manhua"
            suggested_emoji = get_genre_emoji(genre)
        if author and (re.search(r'\d+\s*\]', author) or re.search(r'cap(?:itulo|s)?\.?', author, re.I)):
            author = re.sub(r'^\d+\s*\]\s*', '', author).strip()
            if not author or author.lower() in title.lower():
                author = "Desconocido"

    # 4. Deduplicación Semántica (Título + Autor + Formato)
    stmt_books = select(Book).where(Book.telegram_link_id == link.id)
    b_res = await session.execute(stmt_books)
    all_books = b_res.scalars().all()

    incoming_key = book_identity_key(title, author, ext)
    matching_book = next(
        (b for b in all_books if book_identity_key(b.title, b.author, b.file_format) == incoming_key),
        None,
    )
    if matching_book and matching_book.telegram_message_id:
        if delete_original and link.bot_is_admin:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
            except Exception:
                pass
        msg_link = f"https://t.me/c/{clean_chat_id}/{matching_book.telegram_message_id}"
        return {
            "status": "duplicate",
            "title": matching_book.title,
            "author": matching_book.author,
            "genre": matching_book.genre,
            "publication_year": matching_book.publication_year or "Desconocido",
            "dest_link": msg_link,
            "file_format": matching_book.file_format
        }

    # 5. Reubicación en Forum Topic
    target_message_id = message.message_id
    assigned_topic_id = current_thread_id

    if link.forum_enabled:
        topic_id = await resolve_or_create_topic(
            session=session,
            bot=bot,
            telegram_link=link,
            genre=genre,
            suggested_emoji=suggested_emoji
        )
        assigned_topic_id = topic_id

        if topic_id and current_thread_id != topic_id:
            try:
                reposted_id = await move_or_repost_to_topic(
                    bot=bot,
                    chat_id=chat_id,
                    message_id=message.message_id,
                    topic_id=topic_id,
                    delete_original=(delete_original and link.bot_is_admin)
                )
                if reposted_id:
                    target_message_id = reposted_id
            except ThreadNotFoundError:
                await delete_topic_by_thread_id(session, link.id, topic_id)
                emoji = get_genre_emoji(genre, suggested_emoji)
                new_created = await bot.create_forum_topic(chat_id=chat_id, name=f"{emoji} {genre}"[:128])
                new_topic = Topic(telegram_link_id=link.id, genre=genre, topic_id=new_created.message_thread_id)
                session.add(new_topic)
                await session.commit()
                await session.refresh(new_topic)
                assigned_topic_id = new_created.message_thread_id

                reposted_id = await move_or_repost_to_topic(
                    bot=bot,
                    chat_id=chat_id,
                    message_id=message.message_id,
                    topic_id=new_created.message_thread_id,
                    delete_original=(delete_original and link.bot_is_admin)
                )
                if reposted_id:
                    target_message_id = reposted_id

    # 6. Guardar en Base de Datos
    series_name = classification.get("series_name")
    series_type = classification.get("series_type") or ("Saga" if series_name else "Autoconclusivo")
    series_order = classification.get("series_order")
    series_total = classification.get("series_total")
    has_sequel = classification.get("has_sequel")
    previous_book = classification.get("previous_book")
    next_book = classification.get("next_book")

    new_book = Book(
        user_id=link.user_id,
        title=title,
        author=author,
        genre=genre,
        source="telegram",
        telegram_link_id=link.id,
        telegram_message_id=target_message_id,
        telegram_topic_id=assigned_topic_id,
        telegram_file_id=doc.file_id,
        file_unique_id=file_unique_id,
        file_format=ext,
        publication_year=pub_year,
        series_name=series_name,
        series_type=series_type,
        series_order=series_order,
        series_total=series_total,
        has_sequel=has_sequel,
        previous_book=previous_book,
        next_book=next_book,
        reading_progress=0.0
    )
    session.add(new_book)
    await session.commit()
    await session.refresh(new_book)

    dest_link = f"https://t.me/c/{clean_chat_id}/{target_message_id}"
    return {
        "status": "success",
        "book_id": new_book.id,
        "title": title,
        "author": author,
        "genre": genre,
        "publication_year": pub_year,
        "emoji": suggested_emoji,
        "file_format": ext,
        "dest_link": dest_link,
        "target_message_id": target_message_id,
        "assigned_topic_id": assigned_topic_id,
        "current_thread_id": current_thread_id,
        "series_name": series_name,
        "series_type": series_type,
        "series_order": series_order,
        "series_total": series_total,
        "has_sequel": has_sequel,
        "previous_book": previous_book,
        "next_book": next_book
    }
