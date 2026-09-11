import html
import re
from typing import List, Optional, Dict, Any, Union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.book import Book
from app.services.topic_resolver import normalize_genre_slug
from app.services.ai_classifier import get_genre_emoji, classify_book_with_gemini


def _find_book_in_library(target_title: Optional[str], books: List[Book]) -> Optional[Book]:
    """Busca un libro en la colección por coincidencia de slug normalizado."""
    if not target_title:
        return None
    target_slug = normalize_genre_slug(target_title)
    if not target_slug or len(target_slug) < 3:
        return None

    for b in books:
        b_slug = normalize_genre_slug(b.title)
        if target_slug == b_slug or target_slug in b_slug or b_slug in target_slug:
            return b
    return None


def format_book_full_description(
    book: Union[Book, Dict[str, Any]],
    chat_books: List[Book],
    clean_chat_id: str,
    current_topic_name: Optional[str] = None,
    current_topic_emoji: Optional[str] = None,
    for_caption: bool = False
) -> str:
    """
    Genera la descripción rica y detallada de un libro:
    - Título, autor, año de publicación
    - Ubicación actual (si está en algún tema del foro o en General)
    - Saga, trilogía, bilogía o libro autoconclusivo
    - ¿Tiene continuación? (Sí / No)
    - Libro anterior y libro siguiente, indicando si están en algún tema de la biblioteca o no.
    - Respeta el límite de 1024 caracteres para captions de Telegram.
    """
    # Extraer campos de Book u objeto Dict
    if isinstance(book, Book):
        title = book.title or "Sin título"
        author = book.author or "Desconocido"
        genre = book.genre or "General"
        pub_year = book.publication_year or "Desconocido"
        series_name = book.series_name
        series_type = book.series_type or ("Saga" if series_name else "Autoconclusivo")
        series_order = book.series_order
        series_total = book.series_total
        has_sequel = book.has_sequel
        previous_book = book.previous_book
        next_book = book.next_book
    else:
        title = book.get("title") or "Sin título"
        author = book.get("author") or "Desconocido"
        genre = book.get("genre") or "General"
        pub_year = book.get("publication_year") or "Desconocido"
        series_name = book.get("series_name")
        series_type = book.get("series_type") or ("Saga" if series_name else "Autoconclusivo")
        series_order = book.get("series_order")
        series_total = book.get("series_total")
        has_sequel = book.get("has_sequel")
        previous_book = book.get("previous_book")
        next_book = book.get("next_book")

    title_safe = html.escape(title)
    author_safe = html.escape(author)
    genre_safe = html.escape(current_topic_name or genre)
    topic_emo = current_topic_emoji or get_genre_emoji(genre_safe)

    lines = [
        f"📖 <b>{title_safe}</b>",
        f"✍️ <i>{author_safe}</i>",
        f"🏷️ <b>Tema actual:</b> {topic_emo} <b>{genre_safe}</b>",
        f"📅 <b>Publicación:</b> <code>{pub_year}</code>"
    ]

    is_series = bool(series_name or (series_type and series_type.lower() != "autoconclusivo"))

    if is_series and series_name:
        s_name_safe = html.escape(series_name)
        s_type_safe = html.escape(series_type or "Saga")
        if series_order and series_total:
            order_info = f" (Libro {series_order} de {series_total})"
        elif series_order:
            order_info = f" (Libro #{series_order})"
        else:
            order_info = ""

        lines.append(f"\n📚 <b>{s_type_safe}:</b> {s_name_safe}{order_info}")

        # Indicador de continuación
        if has_sequel:
            lines.append("🔜 <b>Continuación:</b> Sí")
        elif has_sequel is False:
            lines.append(f"🏁 <b>Continuación:</b> No <i>(Libro final de la {s_type_safe.lower()})</i>")

        # Libro anterior y si está en algún tema de la biblioteca o no
        if previous_book:
            prev_safe = html.escape(previous_book)
            match_prev = _find_book_in_library(previous_book, chat_books)
            if match_prev:
                p_emo = get_genre_emoji(match_prev.genre)
                p_genre_safe = html.escape(match_prev.genre)
                if match_prev.telegram_message_id and clean_chat_id:
                    link_url = f"https://t.me/c/{clean_chat_id}/{match_prev.telegram_message_id}"
                    status_prev = f'✅ En biblioteca: {p_emo} <b>{p_genre_safe}</b> (<a href="{link_url}">👉 Ver</a>)'
                else:
                    status_prev = f'✅ En biblioteca: {p_emo} <b>{p_genre_safe}</b>'
            else:
                status_prev = "❌ No está en la biblioteca"

            lines.append(f"⬅️ <b>Anterior:</b> <i>{prev_safe}</i>\n   ↳ {status_prev}")
        elif series_order == 1:
            lines.append("⬅️ <b>Anterior:</b> <i>Ninguno (Primer libro)</i>")

        # Libro siguiente y si está en algún tema de la biblioteca o no
        if next_book:
            next_safe = html.escape(next_book)
            match_next = _find_book_in_library(next_book, chat_books)
            if match_next:
                n_emo = get_genre_emoji(match_next.genre)
                n_genre_safe = html.escape(match_next.genre)
                if match_next.telegram_message_id and clean_chat_id:
                    link_url = f"https://t.me/c/{clean_chat_id}/{match_next.telegram_message_id}"
                    status_next = f'✅ En biblioteca: {n_emo} <b>{n_genre_safe}</b> (<a href="{link_url}">👉 Ver</a>)'
                else:
                    status_next = f'✅ En biblioteca: {n_emo} <b>{n_genre_safe}</b>'
            else:
                status_next = "❌ No está en la biblioteca"

            lines.append(f"➡️ <b>Siguiente:</b> <i>{next_safe}</i>\n   ↳ {status_next}")
        elif has_sequel is False:
            lines.append("➡️ <b>Siguiente:</b> <i>Ninguno (Libro de cierre)</i>")

    else:
        lines.append("\n📚 <b>Obra:</b> Autoconclusiva <i>(Libro único, sin continuación)</i>")

    res = "\n".join(lines)
    if for_caption and len(res) > 1000:
        res = res[:990] + "..."
    return res


async def enrich_book_series_if_needed(book: Book, session: AsyncSession) -> Book:
    """Si el libro no tiene metadatos de saga en la base de datos, los analiza con IA y los guarda."""
    if book.series_type is not None and (book.series_name is not None or book.series_type == "Autoconclusivo"):
        return book

    try:
        data = await classify_book_with_gemini(
            filename=f"{book.title} - {book.author}.{book.file_format or 'pdf'}"
        )
        book.series_name = data.get("series_name")
        book.series_type = data.get("series_type") or ("Saga" if book.series_name else "Autoconclusivo")
        book.series_order = data.get("series_order")
        book.series_total = data.get("series_total")
        book.has_sequel = data.get("has_sequel")
        book.previous_book = data.get("previous_book")
        book.next_book = data.get("next_book")

        session.add(book)
        await session.commit()
        await session.refresh(book)
    except Exception:
        pass
    return book
