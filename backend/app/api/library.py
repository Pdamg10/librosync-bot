import os
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.core.database import get_db
from app.models.book import Book
from app.models.telegram_link import TelegramLink
from app.schemas.book import BookOut, BookUpdate
from app.bot.bot_instance import get_bot_application
from app.services.telegram_service import send_book_document, get_telegram_file_bytes
from app.services.topic_resolver import resolve_or_create_topic

router = APIRouter(prefix="/library", tags=["Library"])

@router.get("", response_model=List[BookOut])
async def list_library(
    user_id: int,
    genre: Optional[str] = None,
    author: Optional[str] = None,
    telegram_link_id: Optional[int] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Obtiene el catálogo de libros del usuario con filtros opcionales."""
    query = select(Book).where(Book.user_id == user_id)

    if genre:
        query = query.where(Book.genre == genre)
    if author:
        query = query.where(Book.author.ilike(f"%{author}%"))
    if telegram_link_id:
        query = query.where(Book.telegram_link_id == telegram_link_id)
    if search:
        query = query.where(
            or_(
                Book.title.ilike(f"%{search}%"),
                Book.author.ilike(f"%{search}%")
            )
        )

    res = await db.execute(query.order_by(Book.uploaded_at.desc()))
    return res.scalars().all()


@router.post("/upload", response_model=BookOut)
async def upload_book_from_app(
    user_id: int = Form(...),
    telegram_link_id: int = Form(...),
    title: str = Form(...),
    author: Optional[str] = Form("Desconocido"),
    genre: Optional[str] = Form("General"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Sube un libro desde la aplicación móvil:
    1. Resuelve el Topic de destino en el chat vinculado.
    2. Envía el archivo vía Telegram Bot API al Topic correspondiente.
    3. Registra la metadata y telegram_file_id en la base de datos.
    """
    # 1. Validar chat vinculado
    stmt = select(TelegramLink).where(
        TelegramLink.id == telegram_link_id,
        TelegramLink.user_id == user_id
    )
    res = await db.execute(stmt)
    link = res.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="Chat de Telegram no vinculado a este usuario")

    # 2. Obtener extensión
    filename = file.filename or f"{title}.pdf"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf"

    # 3. Leer contenido en memoria
    file_bytes = await file.read()
    if len(file_bytes) > 50 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="El archivo excede el límite de 50MB de la Bot API estándar de Telegram."
        )

    bot_app = get_bot_application()
    bot = bot_app.bot

    # 4. Resolver Topic si el chat tiene Forum activado
    topic_id = None
    if link.forum_enabled:
        topic_id = await resolve_or_create_topic(db, bot, link, genre)

    # 5. Enviar a Telegram
    caption = f"📖 **{title}**\n✍️ *{author}*\n🏷️ #{genre.replace(' ', '_')}"
    try:
        sent_message = await send_book_document(
            bot=bot,
            chat_id=link.chat_id,
            document=file_bytes,
            filename=filename,
            caption=caption,
            topic_id=topic_id
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error al enviar archivo a Telegram: {str(e)}")

    telegram_file_id = sent_message.document.file_id if sent_message.document else None
    telegram_message_id = sent_message.message_id

    # 6. Guardar en Base de Datos
    new_book = Book(
        user_id=user_id,
        title=title,
        author=author,
        genre=genre,
        source="app",
        telegram_link_id=link.id,
        telegram_message_id=telegram_message_id,
        telegram_file_id=telegram_file_id,
        file_format=ext,
        reading_progress=0.0
    )
    db.add(new_book)
    await db.commit()
    await db.refresh(new_book)

    return new_book


@router.get("/{book_id}", response_model=BookOut)
async def get_book_detail(book_id: int, db: AsyncSession = Depends(get_db)):
    """Obtiene los detalles de un libro específico."""
    stmt = select(Book).where(Book.id == book_id)
    res = await db.execute(stmt)
    book = res.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Libro no encontrado")
    return book


@router.patch("/{book_id}", response_model=BookOut)
async def update_book(book_id: int, payload: BookUpdate, db: AsyncSession = Depends(get_db)):
    """Actualiza la metadata o progreso de un libro."""
    stmt = select(Book).where(Book.id == book_id)
    res = await db.execute(stmt)
    book = res.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Libro no encontrado")

    if payload.title is not None:
        book.title = payload.title
    if payload.author is not None:
        book.author = payload.author
    if payload.genre is not None:
        book.genre = payload.genre
    if payload.reading_progress is not None:
        book.reading_progress = payload.reading_progress

    await db.commit()
    await db.refresh(book)
    return book


@router.delete("/{book_id}")
async def delete_book(book_id: int, db: AsyncSession = Depends(get_db)):
    """Elimina un libro de la biblioteca."""
    stmt = select(Book).where(Book.id == book_id)
    res = await db.execute(stmt)
    book = res.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Libro no encontrado")

    await db.delete(book)
    await db.commit()
    return {"message": "Libro eliminado"}


@router.get("/{book_id}/file")
async def download_book_file(book_id: int, db: AsyncSession = Depends(get_db)):
    """Descarga el archivo del libro desde Telegram para el lector móvil."""
    stmt = select(Book).where(Book.id == book_id)
    res = await db.execute(stmt)
    book = res.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Libro no encontrado")
    if not book.telegram_file_id:
        raise HTTPException(status_code=404, detail="El libro no cuenta con un archivo asociado en Telegram")

    bot_app = get_bot_application()
    try:
        data, _ = await get_telegram_file_bytes(bot_app.bot, book.telegram_file_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error al descargar archivo desde Telegram: {e}")

    media_type = "application/pdf" if (book.file_format or "").lower() == "pdf" else "application/epub+zip"
    filename = f"{book.title}.{book.file_format or 'pdf'}"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/sync")
async def sync_library(telegram_link_id: int, db: AsyncSession = Depends(get_db)):
    """Sincroniza y depura libros que hayan sido eliminados manualmente de Telegram."""
    stmt = select(TelegramLink).where(TelegramLink.id == telegram_link_id)
    res = await db.execute(stmt)
    link = res.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Vínculo de Telegram no encontrado")

    bot_app = get_bot_application()
    from app.services.book_sync_service import sync_all_library_for_chat
    result = await sync_all_library_for_chat(bot_app.bot, db, link.id, link.chat_id)
    return result

