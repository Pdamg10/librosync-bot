from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from telegram.error import BadRequest

from app.core.database import Base
from app.core.migrations import run_migrations
from app.models.book import Book
from app.models.telegram_link import TelegramLink
from app.models.user import User
from app.services.book_identity import book_identity_key


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(run_migrations)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


async def _make_link(session, chat_id: int = -100123456, user_id: int = 1) -> TelegramLink:
    user = await session.get(User, user_id)
    if not user:
        user = User(id=user_id, nombre=f"User {user_id}")
        session.add(user)
        await session.commit()
    link = TelegramLink(
        user_id=user_id,
        chat_id=chat_id,
        chat_type="group_forum",
        chat_title="Test",
        bot_is_admin=True,
        forum_enabled=True,
    )
    session.add(link)
    await session.commit()
    await session.refresh(link)
    return link


def _admin_context(bot) -> MagicMock:
    context = MagicMock(bot=bot)
    bot.get_chat_member = AsyncMock(return_value=MagicMock(status="administrator"))
    return context


@pytest.mark.asyncio
async def test_dedup_preserves_different_authors_same_title_and_format(session):
    from app.services.book_sync_service import deduplicate_library_for_chat

    link = await _make_link(session)
    b1 = Book(
        user_id=1, title="La Odisea", author="Homero", genre="Clásicos",
        telegram_link_id=link.id, telegram_message_id=10, file_format="epub",
    )
    b2 = Book(
        user_id=1, title="La Odisea", author="Otro Autor", genre="Aventuras",
        telegram_link_id=link.id, telegram_message_id=11, file_format="epub",
    )
    duplicate = Book(
        user_id=1, title="la odisea", author="homero", genre="General",
        telegram_link_id=link.id, telegram_message_id=12, file_format="epub",
    )
    session.add_all([b1, b2, duplicate])
    await session.commit()

    bot = MagicMock()
    bot.delete_message = AsyncMock()
    result = await deduplicate_library_for_chat(bot, session, link.id, link.chat_id)

    assert result["duplicates_removed"] == 1
    remaining = (
        await session.execute(select(Book).where(Book.telegram_link_id == link.id))
    ).scalars().all()
    assert len(remaining) == 2
    assert {b.author for b in remaining} == {"Homero", "Otro Autor"}
    assert all(b.id != duplicate.id for b in remaining)


@pytest.mark.asyncio
async def test_sync_reports_real_purged_count(session):
    from app.services.book_sync_service import sync_all_library_for_chat

    link = await _make_link(session, chat_id=-100555)
    alive = Book(
        user_id=1, title="Vivo", author="Autor", telegram_link_id=link.id,
        telegram_message_id=20, file_format="epub",
    )
    dead = Book(
        user_id=1, title="Borrado", author="Autor", telegram_link_id=link.id,
        telegram_message_id=21, file_format="epub",
    )
    session.add_all([alive, dead])
    await session.commit()

    bot = MagicMock()

    async def edit_markup(chat_id, message_id, reply_markup=None):
        if message_id == 21:
            raise BadRequest("Message to edit not found")
        return True

    bot.edit_message_reply_markup = AsyncMock(side_effect=edit_markup)
    result = await sync_all_library_for_chat(bot, session, link.id, link.chat_id)

    assert result["purged_books"] == 1
    assert result["active_books"] == 1
    remaining = (
        await session.execute(select(Book).where(Book.telegram_link_id == link.id))
    ).scalars().all()
    assert [b.title for b in remaining] == ["Vivo"]


@pytest.mark.asyncio
async def test_document_handler_does_not_autocreate_group_link(session, monkeypatch):
    from app.bot import handlers

    @asynccontextmanager
    async def session_ctx():
        yield session

    monkeypatch.setattr(handlers, "AsyncSessionLocal", session_ctx)

    document = MagicMock()
    document.file_name = "libro.epub"
    document.file_size = 1024
    document.file_id = "file"
    document.file_unique_id = "unique"

    message = MagicMock()
    message.document = document
    message.media_group_id = None
    message.message_thread_id = None

    chat = MagicMock()
    chat.id = -100999123

    update = MagicMock()
    update.effective_message = message
    update.effective_chat = chat
    update.effective_user = MagicMock(id=777)

    bot = MagicMock()
    await handlers.document_handler(update, MagicMock(bot=bot))

    links = (await session.execute(select(TelegramLink))).scalars().all()
    assert links == []


@pytest.mark.asyncio
async def test_non_admin_cannot_run_destructive_command(session, monkeypatch):
    from app.bot import handlers

    @asynccontextmanager
    async def session_ctx():
        yield session

    monkeypatch.setattr(handlers, "AsyncSessionLocal", session_ctx)
    link = await _make_link(session, chat_id=-100777)
    book = Book(
        user_id=1, title="Intacto", author="Autor", telegram_link_id=link.id,
        telegram_message_id=30, file_format="epub",
    )
    session.add(book)
    await session.commit()

    message = MagicMock()
    message.message_thread_id = None
    chat = MagicMock(id=link.chat_id, type="supergroup")
    update = MagicMock(
        callback_query=None,
        effective_message=message,
        effective_chat=chat,
        effective_user=MagicMock(id=999),
    )
    bot = MagicMock()
    bot.get_chat_member = AsyncMock(return_value=MagicMock(status="member"))
    bot.send_message = AsyncMock()

    await handlers.sync_handler(update, MagicMock(bot=bot))

    assert book.id is not None
    sent_text = bot.send_message.call_args.kwargs.get("text", "")
    assert "Permiso denegado" in sent_text
    still_there = (await session.execute(select(Book).where(Book.id == book.id))).scalar_one_or_none()
    assert still_there is not None


@pytest.mark.asyncio
async def test_lost_book_callback_cannot_touch_other_chat(session, monkeypatch):
    from app.bot import handlers

    @asynccontextmanager
    async def session_ctx():
        yield session

    monkeypatch.setattr(handlers, "AsyncSessionLocal", session_ctx)
    link_a = await _make_link(session, chat_id=-100111, user_id=1)
    link_b = await _make_link(session, chat_id=-100222, user_id=2)
    foreign_book = Book(
        user_id=2, title="Ajeno", author="Autor", telegram_link_id=link_b.id,
        telegram_message_id=41, file_format="epub",
    )
    session.add(foreign_book)
    await session.commit()

    query = MagicMock()
    query.data = f"rec:del:{foreign_book.id}"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock(
        callback_query=query,
        effective_chat=MagicMock(id=link_a.chat_id),
        effective_user=MagicMock(id=123),
    )
    bot = MagicMock()
    bot.get_chat_member = AsyncMock(return_value=MagicMock(status="administrator"))

    await handlers.lost_book_callback_handler(update, MagicMock(bot=bot))

    still_there = (
        await session.execute(select(Book).where(Book.id == foreign_book.id))
    ).scalar_one_or_none()
    assert still_there is not None


@pytest.mark.asyncio
async def test_download_token_is_bound_to_chat_and_user():
    import time
    from app.bot import handlers

    token = "scope-test"
    handlers._download_cache[token] = {
        "results": [{"title": "Libro", "format": "epub", "download_url": "https://example.org/a.epub"}],
        "created": time.time(),
        "query": "Libro",
        "chat_id": -100111,
        "user_id": 1,
    }
    query = MagicMock()
    query.data = f"dl:{token}:0"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock(
        callback_query=query,
        effective_chat=MagicMock(id=-100222),
        effective_user=MagicMock(id=2),
    )
    bot = MagicMock()
    try:
        await handlers.download_callback_handler(update, MagicMock(bot=bot))
    finally:
        handlers._download_cache.pop(token, None)

    query.edit_message_text.assert_not_called()
    assert query.answer.await_count >= 1


def test_download_url_validation_rejects_internal_targets():
    from app.services.book_download_service import _validate_remote_url

    assert _validate_remote_url("https://archive.org/download/x.epub").startswith("https://")
    for bad in (
        "file:///etc/passwd",
        "http://localhost/admin",
        "http://127.0.0.1:8000/",
        "http://169.254.169.254/latest/meta-data/",
        "https://user:pass@example.org/book.epub",
    ):
        with pytest.raises(ValueError):
            _validate_remote_url(bad)


@pytest.mark.asyncio
async def test_download_reader_enforces_streaming_size_limit():
    from app.services.book_download_service import _read_limited

    class DeclaredTooLarge:
        headers = {"content-length": "100"}
        content = b"x" * 100

    with pytest.raises(ValueError):
        await _read_limited(DeclaredTooLarge(), 50)

    class ChunkedTooLarge:
        headers = {}

        async def aiter_bytes(self):
            yield b"a" * 30
            yield b"b" * 30

    with pytest.raises(ValueError):
        await _read_limited(ChunkedTooLarge(), 40)


def test_book_identity_distinguishes_author_and_format():
    assert book_identity_key("Dune", "Frank Herbert", "epub") == (
        "dune", "frankherbert", "epub"
    )
    assert book_identity_key("Dune", "Frank Herbert", "epub") != book_identity_key(
        "Dune", "Brian Herbert", "epub"
    )
    assert book_identity_key("Dune", "Frank Herbert", "epub") != book_identity_key(
        "Dune", "Frank Herbert", "pdf"
    )


def test_logging_redacts_tokens_and_api_keys():
    from app.core.logging_config import redact_sensitive

    text = (
        "https://api.telegram.org/bot123456789:AAHfakeTOKENvalue/getMe "
        "https://example.org/?key=SECRET123&x=1 "
        "Authorization: Bearer abcdef"
    )
    cleaned = redact_sensitive(text)
    assert "AAHfakeTOKENvalue" not in cleaned
    assert "SECRET123" not in cleaned
    assert "abcdef" not in cleaned


def test_migrations_are_versioned_and_idempotent():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        run_migrations(conn)
        run_migrations(conn)
        versions = [row[0] for row in conn.exec_driver_sql(
            "SELECT version FROM schema_migrations ORDER BY version"
        )]
    engine.dispose()
    assert versions == [1, 2]


@pytest.mark.asyncio
async def test_my_books_handler_with_co_readers_and_dedup_buddy_reads(session, monkeypatch):
    from app.bot import handlers
    from app.services.buddy_read_service import create_buddy_read, join_buddy_read, update_member_progress
    from app.services.book_sync_service import deduplicate_library_for_chat

    @asynccontextmanager
    async def session_ctx():
        yield session

    monkeypatch.setattr(handlers, "AsyncSessionLocal", session_ctx)

    link = await _make_link(session, chat_id=-100444555, user_id=1)
    user1 = await session.get(User, 1)
    user1.telegram_user_id = 1001
    user2 = User(id=2, nombre="Ana Lectora", telegram_user_id=1002)
    session.add(user2)
    await session.commit()

    b_canon = Book(
        user_id=1, title="El Nombre del Viento", author="Patrick Rothfuss",
        genre="Fantasía", telegram_link_id=link.id, telegram_message_id=101, file_format="epub",
    )
    b_dup = Book(
        user_id=1, title="el nombre del viento", author="patrick rothfuss",
        genre="General", telegram_link_id=link.id, telegram_message_id=102, file_format="epub",
    )
    session.add_all([b_canon, b_dup])
    await session.commit()

    br1 = await create_buddy_read(session, b_canon.id, user1, telegram_link_id=link.id)
    await join_buddy_read(session, br1.id, user2)
    await update_member_progress(session, br1.id, user1.id, 30.0)
    await update_member_progress(session, br1.id, user2.id, 55.0)

    # También crear lectura conjunta en el duplicado con el mismo usuario y progreso mayor
    br2 = await create_buddy_read(session, b_dup.id, user1, telegram_link_id=link.id)
    await update_member_progress(session, br2.id, user1.id, 75.0)

    # 1. Verificar /mislibros con co-lectores activos (sin AttributeError en User)
    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    update = MagicMock(
        effective_message=MagicMock(message_thread_id=None),
        effective_chat=MagicMock(id=link.chat_id, type="supergroup"),
        effective_user=MagicMock(id=1001, first_name="User 1", last_name="", username="user1"),
    )
    await handlers.my_books_handler(update, MagicMock(bot=bot, args=[]))
    assert bot.send_message.called
    shelves_text = bot.send_message.call_args.kwargs["text"]
    assert "Ana Lectora" in shelves_text
    assert "El Nombre del Viento" in shelves_text

    # 2. Verificar que deduplicación fusiona BuddyReads sin MissingGreenlet ni IntegrityError
    dedup_res = await deduplicate_library_for_chat(bot, session, link.id, link.chat_id)
    assert dedup_res["duplicates_removed"] == 1


@pytest.mark.asyncio
async def test_private_chat_search_and_info_scope_and_supported_formats(session, monkeypatch):
    from app.bot import handlers
    from app.services.book_processor import SUPPORTED_EXTENSIONS

    for ext in (".pdf", ".epub", ".mobi", ".azw3", ".cbr", ".cbz"):
        assert ext in SUPPORTED_EXTENSIONS

    @asynccontextmanager
    async def session_ctx():
        yield session

    monkeypatch.setattr(handlers, "AsyncSessionLocal", session_ctx)

    user = User(id=50, nombre="Lector Privado", telegram_user_id=5050)
    priv_link = TelegramLink(
        id=50, user_id=50, chat_id=5050, chat_type="private",
        chat_title="Biblioteca Personal", bot_is_admin=True, forum_enabled=False,
    )
    book = Book(
        user_id=50, title="Watchmen", author="Alan Moore",
        genre="Novela Gráfica", file_format="cbz", publication_year="1986",
        series_type="Autoconclusivo",
    )
    session.add_all([user, priv_link, book])
    await session.commit()

    bot = MagicMock()
    bot.send_message = AsyncMock()
    update = MagicMock(
        effective_message=MagicMock(message_thread_id=None, reply_to_message=None),
        effective_chat=MagicMock(id=5050, type="private"),
        effective_user=MagicMock(id=5050, first_name="Lector"),
    )

    # /buscar en chat privado encuentra libro asociado al user_id
    await handlers.search_handler(update, MagicMock(bot=bot, args=["Watchmen"]))
    assert bot.send_message.called
    assert "Watchmen" in bot.send_message.call_args.kwargs["text"]

    # /info en chat privado encuentra libro asociado al user_id
    bot.send_message.reset_mock()
    await handlers.info_handler(update, MagicMock(bot=bot, args=["Watchmen"]))
    assert bot.send_message.called
    assert "Alan Moore" in bot.send_message.call_args.kwargs["text"]

