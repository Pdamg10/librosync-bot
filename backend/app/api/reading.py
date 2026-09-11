from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.user import User
from app.models.book import Book
from app.models.reading import ReadingState, BuddyRead, BuddyReadMember
from app.schemas.reading import (
    ReadingStateOut,
    ReadingStateUpdate,
    ShelfSummaryOut,
    BuddyReadCreate,
    BuddyReadOut,
    BuddyReadMemberOut
)
from app.services.buddy_read_service import (
    update_user_book_state,
    get_user_reading_shelves,
    create_buddy_read,
    join_buddy_read,
    update_member_progress,
    find_co_readers_for_book
)

router = APIRouter(prefix="/reading", tags=["Reading & Buddy Reads"])


@router.get("/shelves", response_model=ShelfSummaryOut)
async def get_my_shelves(
    user_id: int = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Obtiene los estantes organizados del usuario:
    - Leyendo actualmente (reading)
    - Terminados (finished)
    - Por leer / Deseos (to_read)
    - Libros favoritos (favorites)
    """
    data = await get_user_reading_shelves(db, user_id)
    return data


@router.put("/status", response_model=ReadingStateOut)
async def update_reading_status(
    user_id: int = Query(...),
    book_id: int = Query(...),
    payload: ReadingStateUpdate = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Actualiza el estado de lectura de un libro para el usuario:
    - Cambiar estado: 'reading', 'finished', 'to_read', 'abandoned'
    - Marcar o desmarcar favorito (is_favorite)
    - Actualizar porcentaje de avance (0-100%) o página actual
    """
    # Validar existencia del libro
    b_stmt = select(Book).where(Book.id == book_id)
    book = (await db.execute(b_stmt)).scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Libro no encontrado.")

    state = await update_user_book_state(
        session=db,
        user_id=user_id,
        book_id=book_id,
        status=payload.status,
        is_favorite=payload.is_favorite,
        progress_percent=payload.progress_percent,
        current_page=payload.current_page,
        total_pages=payload.total_pages,
        notes=payload.notes
    )

    # Cargar el libro para la respuesta
    stmt_full = (
        select(ReadingState)
        .options(selectinload(ReadingState.book).selectinload(Book.telegram_link))
        .where(ReadingState.id == state.id)
    )
    res = await db.execute(stmt_full)
    return res.scalar_one()


@router.get("/co-readers/{book_id}")
async def get_co_readers(
    book_id: int,
    exclude_user_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Identifica a otros miembros de la comunidad que están leyendo el mismo libro en este momento.
    """
    co_readers = await find_co_readers_for_book(db, book_id, exclude_user_id)
    return {"book_id": book_id, "count": len(co_readers), "readers": co_readers}


@router.get("/buddy-reads", response_model=List[BuddyReadOut])
async def list_buddy_reads(
    telegram_link_id: Optional[int] = Query(None),
    status: Optional[str] = Query("active"),
    db: AsyncSession = Depends(get_db)
):
    """
    Lista las lecturas conjuntas (por defecto las activas).
    """
    query = (
        select(BuddyRead)
        .options(
            selectinload(BuddyRead.book).selectinload(Book.telegram_link),
            selectinload(BuddyRead.members)
        )
    )
    if telegram_link_id:
        query = query.where(BuddyRead.telegram_link_id == telegram_link_id)
    if status and status != "all":
        query = query.where(BuddyRead.status == status)

    res = await db.execute(query.order_by(BuddyRead.created_at.desc()))
    return res.scalars().all()


@router.post("/buddy-reads", response_model=BuddyReadOut)
async def create_new_buddy_read(
    user_id: int = Query(...),
    payload: BuddyReadCreate = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Inicia una nueva lectura conjunta e incorpora al creador como primer miembro.
    """
    u_stmt = select(User).where(User.id == user_id)
    user = (await db.execute(u_stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    b_stmt = select(Book).where(Book.id == payload.book_id)
    book = (await db.execute(b_stmt)).scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Libro no encontrado.")

    br = await create_buddy_read(
        session=db,
        book_id=payload.book_id,
        creator_user=user,
        telegram_link_id=payload.telegram_link_id,
        title=payload.title
    )

    stmt_full = (
        select(BuddyRead)
        .options(
            selectinload(BuddyRead.book).selectinload(Book.telegram_link),
            selectinload(BuddyRead.members)
        )
        .where(BuddyRead.id == br.id)
    )
    return (await db.execute(stmt_full)).scalar_one()


@router.post("/buddy-reads/{buddy_read_id}/join", response_model=BuddyReadMemberOut)
async def join_active_buddy_read(
    buddy_read_id: int,
    user_id: int = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Une al usuario a una lectura conjunta activa.
    """
    u_stmt = select(User).where(User.id == user_id)
    user = (await db.execute(u_stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    br_stmt = select(BuddyRead).where(BuddyRead.id == buddy_read_id)
    br = (await db.execute(br_stmt)).scalar_one_or_none()
    if not br:
        raise HTTPException(status_code=404, detail="Lectura conjunta no encontrada.")

    member, _ = await join_buddy_read(db, buddy_read_id, user)
    return member


@router.put("/buddy-reads/{buddy_read_id}/progress", response_model=BuddyReadMemberOut)
async def update_my_buddy_progress(
    buddy_read_id: int,
    user_id: int = Query(...),
    progress_percent: float = Query(...),
    current_page: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Actualiza el porcentaje de lectura del usuario en una lectura conjunta y su estante personal.
    """
    member = await update_member_progress(
        session=db,
        buddy_read_id=buddy_read_id,
        user_id=user_id,
        progress_percent=progress_percent,
        current_page=current_page
    )
    if not member:
        raise HTTPException(status_code=404, detail="El usuario no es miembro de esta lectura conjunta.")
    return member
