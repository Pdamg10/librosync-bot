import html
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, User as TgUser

from app.models.user import User
from app.models.book import Book
from app.models.reading import ReadingState, BuddyRead, BuddyReadMember
from app.services.ai_classifier import get_genre_emoji


def utc_now():
    return datetime.now(timezone.utc)


def format_progress_bar(percent: float, length: int = 10) -> str:
    """Genera una barra de progreso visual en texto (ej. [████░░░░░░] 40%)."""
    clamped = max(0.0, min(100.0, float(percent or 0.0)))
    filled = int(round((clamped / 100.0) * length))
    filled = max(0, min(length, filled))
    empty = length - filled
    bar = "█" * filled + "░" * empty
    return f"[{bar}] {int(clamped)}%"


async def get_or_create_user_from_telegram(session: AsyncSession, tg_user: TgUser) -> User:
    """
    Obtiene o crea un usuario de LibroSync a partir de un usuario de Telegram.
    Garantiza persistencia y trazabilidad entre Telegram y la App móvil.
    """
    stmt = select(User).where(User.telegram_user_id == tg_user.id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()

    full_name = f"{tg_user.first_name or ''} {tg_user.last_name or ''}".strip() or (tg_user.username or f"Usuario_{tg_user.id}")

    if not user:
        user = User(
            nombre=full_name,
            telegram_user_id=tg_user.id
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    else:
        # Actualizar nombre si cambió
        if full_name and user.nombre != full_name:
            user.nombre = full_name
            await session.commit()
            await session.refresh(user)

    return user


async def update_user_book_state(
    session: AsyncSession,
    user_id: int,
    book_id: int,
    status: Optional[str] = None,
    is_favorite: Optional[bool] = None,
    progress_percent: Optional[float] = None,
    current_page: Optional[int] = None,
    total_pages: Optional[int] = None,
    notes: Optional[str] = None
) -> ReadingState:
    """
    Crea o actualiza el estado de lectura y estantes personales de un usuario para un libro.
    """
    stmt = select(ReadingState).where(
        ReadingState.user_id == user_id,
        ReadingState.book_id == book_id
    )
    res = await session.execute(stmt)
    state = res.scalar_one_or_none()

    now = utc_now()
    if not state:
        state = ReadingState(
            user_id=user_id,
            book_id=book_id,
            status=status or "to_read",
            is_favorite=is_favorite if is_favorite is not None else False,
            progress_percent=progress_percent if progress_percent is not None else 0.0,
            current_page=current_page,
            total_pages=total_pages,
            notes=notes,
            created_at=now,
            updated_at=now
        )
        if state.status == "reading":
            state.started_at = now
        elif state.status == "finished" or (state.progress_percent and state.progress_percent >= 100.0):
            state.status = "finished"
            state.finished_at = now
        session.add(state)
    else:
        if status is not None:
            state.status = status
            if status == "reading" and not state.started_at:
                state.started_at = now
            elif status == "finished" and not state.finished_at:
                state.finished_at = now
                state.progress_percent = 100.0

        if is_favorite is not None:
            state.is_favorite = is_favorite

        if progress_percent is not None:
            clamped = max(0.0, min(100.0, float(progress_percent)))
            state.progress_percent = clamped
            if clamped >= 100.0 and state.status != "finished":
                state.status = "finished"
                state.finished_at = now
            elif clamped > 0.0 and state.status == "to_read":
                state.status = "reading"
                state.started_at = now

        if current_page is not None:
            state.current_page = current_page
        if total_pages is not None:
            state.total_pages = total_pages
        if notes is not None:
            state.notes = notes

        state.updated_at = now

    await session.commit()
    await session.refresh(state)
    return state


async def get_user_reading_shelves(session: AsyncSession, user_id: int) -> Dict[str, Any]:
    """
    Obtiene todos los estantes de lectura del usuario:
    - Leyendo (reading)
    - Terminados (finished)
    - Por leer (to_read)
    - Favoritos (is_favorite = True)
    """
    stmt = (
        select(ReadingState)
        .options(selectinload(ReadingState.book).selectinload(Book.telegram_link))
        .where(ReadingState.user_id == user_id)
        .order_by(ReadingState.updated_at.desc())
    )
    res = await session.execute(stmt)
    states = res.scalars().all()

    reading = [s for s in states if s.status == "reading"]
    finished = [s for s in states if s.status == "finished"]
    to_read = [s for s in states if s.status == "to_read"]
    favorites = [s for s in states if s.is_favorite]

    return {
        "reading": reading,
        "finished": finished,
        "to_read": to_read,
        "favorites": favorites,
        "total_tracked": len(states)
    }


async def create_buddy_read(
    session: AsyncSession,
    book_id: int,
    creator_user: User,
    telegram_link_id: Optional[int] = None,
    thread_id: Optional[int] = None,
    title: Optional[str] = None,
    tg_user: Optional[TgUser] = None
) -> BuddyRead:
    """
    Inicia una nueva lectura conjunta con el creador como primer miembro.
    """
    buddy_read = BuddyRead(
        book_id=book_id,
        telegram_link_id=telegram_link_id,
        creator_user_id=creator_user.id,
        title=title,
        status="active",
        telegram_thread_id=thread_id,
        created_at=utc_now()
    )
    session.add(buddy_read)
    await session.flush()

    # Añadir al creador como primer miembro
    tg_uname = getattr(tg_user, "username", None) if tg_user else None
    tg_uid = getattr(tg_user, "id", None) if tg_user else creator_user.telegram_user_id

    member = BuddyReadMember(
        buddy_read_id=buddy_read.id,
        user_id=creator_user.id,
        telegram_user_id=tg_uid,
        telegram_username=f"@{tg_uname}" if tg_uname else None,
        telegram_name=creator_user.nombre,
        progress_percent=0.0,
        status="reading",
        joined_at=utc_now(),
        last_progress_at=utc_now()
    )
    session.add(member)

    # Actualizar estado individual del creador
    await update_user_book_state(session, creator_user.id, book_id, status="reading")

    await session.commit()
    stmt_full = (
        select(BuddyRead)
        .options(selectinload(BuddyRead.members), selectinload(BuddyRead.book).selectinload(Book.telegram_link))
        .where(BuddyRead.id == buddy_read.id)
    )
    return (await session.execute(stmt_full)).scalar_one()


async def join_buddy_read(
    session: AsyncSession,
    buddy_read_id: int,
    user: User,
    tg_user: Optional[TgUser] = None
) -> Tuple[BuddyReadMember, bool]:
    """
    Une a un usuario a una lectura conjunta activa.
    Retorna (member, was_created).
    """
    stmt = select(BuddyReadMember).where(
        BuddyReadMember.buddy_read_id == buddy_read_id,
        BuddyReadMember.user_id == user.id
    )
    res = await session.execute(stmt)
    existing = res.scalar_one_or_none()

    if existing:
        return existing, False

    tg_uname = getattr(tg_user, "username", None) if tg_user else None
    tg_uid = getattr(tg_user, "id", None) if tg_user else user.telegram_user_id

    new_member = BuddyReadMember(
        buddy_read_id=buddy_read_id,
        user_id=user.id,
        telegram_user_id=tg_uid,
        telegram_username=f"@{tg_uname}" if tg_uname else None,
        telegram_name=user.nombre,
        progress_percent=0.0,
        status="reading",
        joined_at=utc_now(),
        last_progress_at=utc_now()
    )
    session.add(new_member)

    # Sincronizar con el estante personal del usuario
    stmt_br = select(BuddyRead).where(BuddyRead.id == buddy_read_id)
    br = (await session.execute(stmt_br)).scalar_one_or_none()
    if br:
        await update_user_book_state(session, user.id, br.book_id, status="reading")

    await session.commit()
    if br:
        await session.refresh(br, ["members"])
    await session.refresh(new_member)
    return new_member, True


async def update_member_progress(
    session: AsyncSession,
    buddy_read_id: int,
    user_id: int,
    progress_percent: float,
    current_page: Optional[int] = None
) -> Optional[BuddyReadMember]:
    """
    Actualiza el progreso de un miembro en la lectura conjunta y lo sincroniza en su estante personal.
    """
    stmt = select(BuddyReadMember).where(
        BuddyReadMember.buddy_read_id == buddy_read_id,
        BuddyReadMember.user_id == user_id
    )
    res = await session.execute(stmt)
    member = res.scalar_one_or_none()
    if not member:
        return None

    clamped = max(0.0, min(100.0, float(progress_percent)))
    member.progress_percent = clamped
    member.last_progress_at = utc_now()
    if current_page is not None:
        member.current_page = current_page

    if clamped >= 100.0:
        member.status = "finished"
    else:
        member.status = "reading"

    # Sincronizar en estante personal
    stmt_br = select(BuddyRead).where(BuddyRead.id == buddy_read_id)
    br = (await session.execute(stmt_br)).scalar_one_or_none()
    if br:
        await update_user_book_state(
            session=session,
            user_id=user_id,
            book_id=br.book_id,
            progress_percent=clamped,
            current_page=current_page,
            status="finished" if clamped >= 100.0 else "reading"
        )

    await session.commit()
    await session.refresh(member)
    return member


async def find_active_buddy_reads_for_book(
    session: AsyncSession,
    book_id: int,
    telegram_link_id: Optional[int] = None
) -> List[BuddyRead]:
    """Encuentra lecturas conjuntas activas de un libro."""
    stmt = (
        select(BuddyRead)
        .options(selectinload(BuddyRead.members), selectinload(BuddyRead.book))
        .where(BuddyRead.book_id == book_id, BuddyRead.status == "active")
    )
    if telegram_link_id:
        stmt = stmt.where(BuddyRead.telegram_link_id == telegram_link_id)

    res = await session.execute(stmt.order_by(BuddyRead.created_at.desc()))
    return res.scalars().all()


async def find_co_readers_for_book(
    session: AsyncSession,
    book_id: int,
    exclude_user_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Encuentra a todos los usuarios que actualmente están leyendo el libro (en lectura conjunta o individualmente).
    """
    stmt = (
        select(ReadingState)
        .options(selectinload(ReadingState.user))
        .where(
            ReadingState.book_id == book_id,
            ReadingState.status == "reading"
        )
    )
    if exclude_user_id:
        stmt = stmt.where(ReadingState.user_id != exclude_user_id)

    res = await session.execute(stmt.order_by(ReadingState.updated_at.desc()))
    states = res.scalars().all()

    readers = []
    for s in states:
        u_name = s.user.nombre if s.user else "Lector anónimo"
        readers.append({
            "user_id": s.user_id,
            "name": u_name,
            "progress_percent": s.progress_percent,
            "progress_bar": format_progress_bar(s.progress_percent),
            "current_page": s.current_page,
            "updated_at": s.updated_at
        })
    return readers


def format_buddy_read_card(
    buddy_read: BuddyRead,
    book: Book,
    members: List[BuddyReadMember],
    chat_id: Optional[int] = None
) -> Tuple[str, InlineKeyboardMarkup]:
    """
    Formatea la tarjeta interactiva de lectura conjunta para Telegram con barras de progreso y botones de acción.
    """
    emo = get_genre_emoji(book.genre)
    title_safe = html.escape(book.title or "Sin título")
    author_safe = html.escape(book.author or "Desconocido")
    genre_safe = html.escape(book.genre or "General")

    total_members = len(members)
    finished_count = sum(1 for m in members if m.progress_percent >= 100.0)

    lines = [
        "📖 <b>LECTURA CONJUNTA EN CURSO</b>",
        f"<i>(Participantes: {total_members} lectores | {finished_count} terminados)</i>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n",
        f"📚 <b>{title_safe}</b>",
        f"✍️ <i>{author_safe}</i> | 🏷️ {emo} <b>{genre_safe}</b>\n",
        "👥 <b>Progreso de los Lectores:</b>"
    ]

    # Ordenar por progreso descendente
    sorted_members = sorted(members, key=lambda m: m.progress_percent, reverse=True)
    for m in sorted_members:
        bar = format_progress_bar(m.progress_percent, length=8)
        u_display = html.escape(m.telegram_name or m.telegram_username or f"Usuario {m.user_id}")
        status_icon = "🏆" if m.progress_percent >= 100.0 else "📖"
        page_str = f" (pág. {m.current_page})" if m.current_page else ""
        lines.append(f"• {status_icon} <b>{u_display}</b>: {bar}{page_str}")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>¡Únete a la lectura o actualiza tu avance tocando los botones de abajo!</i>")

    buttons = [
        [
            InlineKeyboardButton("🤝 ¡Unirme a leer!", callback_data=f"br:join:{buddy_read.id}"),
            InlineKeyboardButton("📈 Actualizar mi progreso", callback_data=f"br:prog:{buddy_read.id}")
        ],
        [
            InlineKeyboardButton("⭐ Marcar Favorito", callback_data=f"rs:fav:{book.id}"),
            InlineKeyboardButton("🔄 Refrescar avance", callback_data=f"br:card:{buddy_read.id}")
        ]
    ]

    if book.telegram_message_id and chat_id and str(chat_id).startswith("-100"):
        clean_c = str(chat_id).replace("-100", "").replace("-", "")
        book_url = f"https://t.me/c/{clean_c}/{book.telegram_message_id}"
        buttons.append([InlineKeyboardButton("📖 Ir al archivo del libro", url=book_url)])

    return "\n".join(lines), InlineKeyboardMarkup(buttons)


def build_progress_keyboard(buddy_read_id: int) -> InlineKeyboardMarkup:
    """Teclado interactivo para seleccionar el porcentaje de avance rápido."""
    buttons = [
        [
            InlineKeyboardButton("10%", callback_data=f"br:setp:{buddy_read_id}:10"),
            InlineKeyboardButton("25%", callback_data=f"br:setp:{buddy_read_id}:25"),
            InlineKeyboardButton("40%", callback_data=f"br:setp:{buddy_read_id}:40"),
            InlineKeyboardButton("50%", callback_data=f"br:setp:{buddy_read_id}:50"),
        ],
        [
            InlineKeyboardButton("60%", callback_data=f"br:setp:{buddy_read_id}:60"),
            InlineKeyboardButton("75%", callback_data=f"br:setp:{buddy_read_id}:75"),
            InlineKeyboardButton("90%", callback_data=f"br:setp:{buddy_read_id}:90"),
            InlineKeyboardButton("100% 🏆", callback_data=f"br:setp:{buddy_read_id}:100"),
        ],
        [
            InlineKeyboardButton("➕ 5%", callback_data=f"br:incp:{buddy_read_id}:5"),
            InlineKeyboardButton("➕ 10%", callback_data=f"br:incp:{buddy_read_id}:10"),
            InlineKeyboardButton("⬅️ Volver a la tarjeta", callback_data=f"br:card:{buddy_read_id}")
        ]
    ]
    return InlineKeyboardMarkup(buttons)
