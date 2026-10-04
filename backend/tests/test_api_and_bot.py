import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from unittest.mock import AsyncMock, MagicMock

from app.core.database import Base, get_db
from app.main import app
from app.models.user import User
from app.models.telegram_link import TelegramLink
from app.models.topic import Topic
from app.models.book import Book
from app.services.topic_resolver import resolve_or_create_topic, normalize_genre_slug
from app.services.ai_classifier import classify_book_with_gemini, fallback_parse_filename

# Test database in-memory
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

@pytest_asyncio.fixture
async def test_session():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_session):
    if not hasattr(app, "dependency_overrides"):
        pytest.skip("FastAPI app migrado a servicio nativo puro en app.main")
    async def override_get_db():
        yield test_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_generate_link_code(client, test_session):
    response = await client.post("/auth/telegram/link-code", json={"user_id": 1})
    assert response.status_code == 200
    data = response.json()
    assert "code" in data
    assert "deep_link" in data
    assert data["code"] in data["deep_link"]


@pytest.mark.asyncio
async def test_topic_resolver_caching_and_slug_match(test_session):
    user = User(id=1, nombre="Test User")
    test_session.add(user)
    await test_session.commit()

    link = TelegramLink(
        user_id=1,
        chat_id=-1001234567890,
        chat_type="group_forum",
        chat_title="Biblioteca Club",
        bot_is_admin=True,
        forum_enabled=True
    )
    test_session.add(link)
    await test_session.commit()
    await test_session.refresh(link)

    mock_bot = MagicMock()
    mock_topic_result = MagicMock()
    mock_topic_result.message_thread_id = 42
    mock_bot.create_forum_topic = AsyncMock(return_value=mock_topic_result)

    # 1. Crear topic inicial "Dark Romance" -> thread 42
    thread_id = await resolve_or_create_topic(test_session, mock_bot, link, "Dark Romance")
    assert thread_id == 42
    assert mock_bot.create_forum_topic.call_count == 1

    # 2. Petición con variante slug "darkromance" -> debe hacer match y reutilizar thread 42
    matched_thread_id = await resolve_or_create_topic(test_session, mock_bot, link, "darkromance")
    assert matched_thread_id == 42
    assert mock_bot.create_forum_topic.call_count == 1  # Cero llamadas extra

    # 3. Petición con variante "#Dark_Romance" -> debe hacer match
    matched_thread_id_2 = await resolve_or_create_topic(test_session, mock_bot, link, "#Dark_Romance")
    assert matched_thread_id_2 == 42
    assert mock_bot.create_forum_topic.call_count == 1


@pytest.mark.asyncio
async def test_slug_normalization():
    assert normalize_genre_slug("Dark Romance") == "darkromance"
    assert normalize_genre_slug("#darkromance") == "darkromance"
    assert normalize_genre_slug("Ciencia Ficción") == "cienciaficcion"
    assert normalize_genre_slug("Fantasía & Aventuras!") == "fantasiaaventuras"


@pytest.mark.asyncio
async def test_ai_classification_with_existing_topics():
    # Test real contra Gemini usando la API key provista
    res = await classify_book_with_gemini(
        filename="01 - Espinas De Lujuria - Eva Winners.epub",
        caption="",
        existing_topics=["Dark Romance", "Terror", "Ciencia Ficción"]
    )
    assert "title" in res
    assert "author" in res
    assert res["author"] == "Eva Winners"
    # Debe haber seleccionado el topic existente más afín
    assert res["genre"] == "Dark Romance"


@pytest.mark.asyncio
async def test_library_crud(client, test_session):
    user = User(id=1, nombre="Test User")
    test_session.add(user)
    await test_session.commit()

    book = Book(
        user_id=1,
        title="Dune",
        author="Frank Herbert",
        genre="Ciencia Ficción",
        source="telegram",
        file_format="epub"
    )
    test_session.add(book)
    await test_session.commit()
    await test_session.refresh(book)

    res = await client.get("/library?user_id=1")
    assert res.status_code == 200
    books = res.json()
    assert len(books) == 1
    assert books[0]["title"] == "Dune"

    patch_res = await client.patch(f"/library/{book.id}", json={"reading_progress": 0.45})
    assert patch_res.status_code == 200
    assert patch_res.json()["reading_progress"] == 0.45

    del_res = await client.delete(f"/library/{book.id}")
    assert del_res.status_code == 200

    get_res = await client.get(f"/library/{book.id}")
    assert get_res.status_code == 404


@pytest.mark.asyncio
async def test_duplicate_book_detection(test_session):
    user = User(id=1, nombre="Test User")
    test_session.add(user)
    await test_session.commit()

    link = TelegramLink(
        user_id=1,
        chat_id=-1001234567890,
        chat_type="group_forum",
        chat_title="Biblioteca Club",
        bot_is_admin=True,
        forum_enabled=True
    )
    test_session.add(link)
    await test_session.commit()
    await test_session.refresh(link)

    # Insertar libro base
    book1 = Book(
        user_id=1,
        title="Espinas De Lujuria",
        author="Eva Winners",
        genre="Dark Romance",
        source="telegram",
        telegram_link_id=link.id,
        telegram_message_id=500,
        telegram_file_id="FILE_ID_1",
        file_unique_id="UNIQUE_HASH_123",
        file_format="epub"
    )
    test_session.add(book1)
    await test_session.commit()

    # 1. Simular comprobación por file_unique_id
    stmt = select(Book).where(
        Book.telegram_link_id == link.id,
        Book.file_unique_id == "UNIQUE_HASH_123"
    )
    res = await test_session.execute(stmt)
    found_dup = res.scalar_one_or_none()
    assert found_dup is not None
    assert found_dup.title == "Espinas De Lujuria"

    # 2. Simular comprobación semántica por título
    slug_incoming = normalize_genre_slug("01 - Espinas De Lujuria")
    assert normalize_genre_slug(found_dup.title) in slug_incoming or slug_incoming in normalize_genre_slug(found_dup.title)


def test_fallback_parse_filename():
    # Caso 1: Con hint del tema actual
    res1 = fallback_parse_filename("01 - Mi Secreto - Jane Doe.pdf", current_topic_hint="Dark Romance")
    assert res1["genre"] == "Dark Romance"
    assert res1["title"] == "Mi Secreto"
    assert res1["author"] == "Jane Doe"
    assert res1["emoji"] == "🖤"

    # Caso 2: Coincidencia por palabra clave de tema existente
    existing = ["Dark Romance", "Ciencia Ficción", "Fantasía"]
    res2 = fallback_parse_filename("El Dragon Y La Magia - Autor.epub", existing_topics=existing)
    assert res2["genre"] == "Fantasía"
    assert res2["title"] == "El Dragon Y La Magia"
    assert res2["author"] == "Autor"

    # Caso 3: Coincidencia de slug directo
    res3 = fallback_parse_filename("dark romance especial.pdf", existing_topics=existing)
    assert res3["genre"] == "Dark Romance"

    # Caso 4: Libro de Fantasía subido por error en Romance -> Debe clasificar como Fantasía
    res4 = fallback_parse_filename(
        "Harry Potter y el Caliz de Fuego.epub",
        existing_topics=["Romance", "Fantasía"],
        current_topic_hint="Romance"
    )
    assert res4["genre"] == "Fantasía"
    assert res4["emoji"] == "🧙"


@pytest.mark.asyncio
async def test_gemini_retry_on_429():
    import httpx
    from unittest.mock import patch, AsyncMock

    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.text = "RESOURCE_EXHAUSTED"

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{
                    "text": '{"title": "Cien Años de Soledad", "author": "Gabriel García Márquez", "genre": "Fantasía", "emoji": "🧙"}'
                }]
            }
        }]
    }

    mock_client = AsyncMock()
    # Primera llamada da 429, segunda da 200
    mock_client.post.side_effect = [mock_resp_429, mock_resp_200]

    with patch("httpx.AsyncClient") as mock_client_cls, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        res = await classify_book_with_gemini("Cien Años de Soledad.epub")
        assert res["title"] == "Cien Años de Soledad"
        assert res["author"] == "Gabriel García Márquez"
        assert res["genre"] == "Fantasía"
        assert mock_client.post.call_count == 2


@pytest.mark.asyncio
async def test_misplaced_book_reclassification_and_relocation(test_session):
    # Link
    link = TelegramLink(
        user_id=1,
        chat_id=-100999888,
        chat_type="group_forum",
        chat_title="Comunidad Libros",
        bot_is_admin=True,
        forum_enabled=True
    )
    test_session.add(link)
    await test_session.commit()
    await test_session.refresh(link)

    # Temas existentes: Romance (thread 19) y Fantasía (thread 18)
    t_romance = Topic(telegram_link_id=link.id, genre="Romance", topic_id=19)
    t_fantasia = Topic(telegram_link_id=link.id, genre="Fantasía", topic_id=18)
    test_session.add_all([t_romance, t_fantasia])
    await test_session.commit()

    # Libro registrado originalmente por error en Romance
    book = Book(
        user_id=1,
        title="Harry Potter y el Prisionero de Azkaban",
        author="J.K. Rowling",
        genre="Romance",
        source="telegram",
        telegram_link_id=link.id,
        telegram_message_id=1001,
        telegram_file_id="HP3_FILE_ID",
        file_unique_id="HP3_UNIQUE",
        file_format="epub"
    )
    test_session.add(book)
    await test_session.commit()
    await test_session.refresh(book)

    # Supongamos que se reevalúa el libro:
    # La clasificación detecta objetivamente Fantasía
    detected_genre = "Fantasía"
    assert normalize_genre_slug(book.genre) != normalize_genre_slug(detected_genre)

    # Resolver el topic correcto
    mock_bot = AsyncMock()
    correct_topic_id = await resolve_or_create_topic(
        session=test_session,
        bot=mock_bot,
        telegram_link=link,
        genre=detected_genre
    )
    assert correct_topic_id == 18

    # Verificar que el hilo actual (19 - Romance) no coincide con el correcto (18 - Fantasía)
    origin_thread_id = 19
    assert origin_thread_id != correct_topic_id

    # Actualizar registro en BD (simulando reubicación)
    book.genre = detected_genre
    book.telegram_message_id = 1002  # Nuevo message_id en el topic 18
    await test_session.commit()
    await test_session.refresh(book)

    assert book.genre == "Fantasía"
    assert book.telegram_message_id == 1002


def test_catalog_pagination_and_html_escaping():
    from app.bot.handlers import build_catalog_page
    from datetime import datetime, timezone

    books = [
        Book(
            user_id=1,
            title=f"Libro <Especial> #{i}_test",
            author=f"Autor & Cía {i}",
            genre="Ficción",
            publication_year="2020",
            uploaded_at=datetime.now(timezone.utc),
            file_format="epub",
            telegram_message_id=500 + i
        )
        for i in range(1, 13)
    ]

    # Página 1 de 3 (12 libros, 5 por página)
    text_p1, kb_p1 = build_catalog_page(chat_id=-100123456, books=books, page=1, per_page=5)
    assert "Página 1 de 3" in text_p1
    assert "12 libros registrados" in text_p1
    assert "&lt;Especial&gt;" in text_p1  # HTML safe
    assert "Autor &amp; Cía" in text_p1
    assert "📅 Publicación: <code>2020</code>" in text_p1
    # Botones: No hay 'Anterior', hay 'Página 1/3' y 'Siguiente'
    btn_callbacks_p1 = [b.callback_data for row in kb_p1.inline_keyboard for b in row]
    assert "catalog:page:2" in btn_callbacks_p1
    assert "catalog:page:0" not in btn_callbacks_p1

    # Página 2 de 3
    text_p2, kb_p2 = build_catalog_page(chat_id=-100123456, books=books, page=2, per_page=5)
    assert "Página 2 de 3" in text_p2
    btn_callbacks_p2 = [b.callback_data for row in kb_p2.inline_keyboard for b in row]
    assert "catalog:page:1" in btn_callbacks_p2
    assert "catalog:page:3" in btn_callbacks_p2

    # Página 3 de 3
    text_p3, kb_p3 = build_catalog_page(chat_id=-100123456, books=books, page=3, per_page=5)
    assert "Página 3 de 3" in text_p3
    btn_callbacks_p3 = [b.callback_data for row in kb_p3.inline_keyboard for b in row]
    assert "catalog:page:2" in btn_callbacks_p3
    assert "catalog:page:4" not in btn_callbacks_p3


@pytest.mark.asyncio
async def test_download_book_file(client, test_session, monkeypatch):
    user = User(id=1, nombre="Test User")
    test_session.add(user)
    await test_session.commit()

    book = Book(
        user_id=1,
        title="Libro Descargable",
        author="Autor Pro",
        genre="Fantasía",
        telegram_file_id="BQACAgEAAxkBAAI...",
        file_format="pdf"
    )
    test_session.add(book)
    await test_session.commit()
    await test_session.refresh(book)

    from unittest.mock import AsyncMock
    async def mock_get_bytes(bot, file_id):
        return b"%PDF-1.4 test content", "file.pdf"

    monkeypatch.setattr("app.api.library.get_telegram_file_bytes", mock_get_bytes)

    res = await client.get(f"/library/{book.id}/file")
    assert res.status_code == 200
    assert res.content == b"%PDF-1.4 test content"
    assert "application/pdf" in res.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_sync_and_purge_deleted_books(client, test_session, monkeypatch):
    from app.services.book_sync_service import purge_deleted_books_for_chat, sync_all_library_for_chat
    from telegram.error import BadRequest

    user = User(id=99, nombre="Sync User")
    test_session.add(user)
    await test_session.commit()

    link = TelegramLink(
        id=99,
        user_id=99,
        chat_id=-100999999,
        chat_type="group_forum",
        chat_title="Test Forum",
        bot_is_admin=True,
        forum_enabled=True
    )
    test_session.add(link)
    await test_session.commit()

    # Create 1 alive book (msg 101) and 1 dead book (msg 102)
    b_alive = Book(user_id=99, title="Libro Vivo", telegram_link_id=99, telegram_message_id=101, genre="Romance")
    b_dead = Book(user_id=99, title="Libro Borrado", telegram_link_id=99, telegram_message_id=102, genre="Romance")
    test_session.add_all([b_alive, b_dead])
    await test_session.commit()

    class MockBot:
        async def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None):
            if message_id == 102:
                raise BadRequest("Message to edit not found")
            return True

        async def edit_forum_topic(self, chat_id, message_thread_id, name):
            return True

    mock_bot = MockBot()

    purged = await purge_deleted_books_for_chat(mock_bot, test_session, link.id, link.chat_id)
    assert purged == 1

    # Verify only b_alive remains in DB
    remaining = (await test_session.execute(select(Book).where(Book.telegram_link_id == link.id))).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].title == "Libro Vivo"


@pytest.mark.asyncio
async def test_multiple_books_batch_processing(test_session, monkeypatch):
    """Verifica que un lote de múltiples libros (ej: 5 libros enviados simultáneamente) se procese y registre por completo."""
    from app.services.book_processor import process_book_message, get_chat_lock
    from telegram import Document

    user = User(id=77, nombre="Batch User")
    test_session.add(user)
    await test_session.commit()

    link = TelegramLink(
        id=77,
        user_id=77,
        chat_id=-100777777,
        chat_type="group_forum",
        chat_title="Batch Forum",
        bot_is_admin=True,
        forum_enabled=True
    )
    test_session.add(link)
    await test_session.commit()

    # Simular clasificación sin consumir cuotas de API
    async def mock_classify(filename, caption=None, existing_topics=None, current_topic_hint=None, **kwargs):
        clean = filename.rsplit(".", 1)[0].replace("_", " ")
        genre = "Fantasía" if "potter" in clean.lower() else "Ciencia Ficción"
        return {
            "title": clean,
            "author": "Autor Batch",
            "genre": genre,
            "emoji": "🧙" if genre == "Fantasía" else "🚀"
        }

    monkeypatch.setattr("app.services.book_processor.classify_book_with_gemini", mock_classify)

    class MockBatchBot:
        id = 8671412842
        async def copy_message(self, chat_id, from_chat_id, message_id, message_thread_id=None):
            m = MagicMock()
            m.message_id = 9000 + message_id
            return m
        async def delete_message(self, chat_id, message_id):
            return True
        async def create_forum_topic(self, chat_id, name):
            t = MagicMock()
            t.message_thread_id = 555
            return t

    mock_bot = MockBatchBot()

    # 5 libros enviados en lote
    filenames = [
        "Harry Potter 1.epub",
        "Harry Potter 2.epub",
        "Harry Potter 3.epub",
        "Dune.epub",
        "Fundacion.pdf"
    ]

    results = []
    async with get_chat_lock(link.chat_id):
        for idx, fname in enumerate(filenames, start=1):
            mock_msg = MagicMock()
            mock_msg.message_id = 1000 + idx
            mock_msg.message_thread_id = None
            mock_msg.caption = None
            mock_msg.document = MagicMock()
            mock_msg.document.file_name = fname
            mock_msg.document.file_id = f"file_id_{idx}"
            mock_msg.document.file_unique_id = f"uniq_id_{idx}"

            res = await process_book_message(
                bot=mock_bot,
                session=test_session,
                link=link,
                chat_id=link.chat_id,
                message=mock_msg,
                delete_original=True
            )
            results.append(res)

    # Verificar que los 5 libros se registraron exitosamente
    assert len(results) == 5
    for r in results:
        assert r["status"] == "success"
        assert r["dest_link"] is not None

    db_books = (await test_session.execute(select(Book).where(Book.telegram_link_id == link.id))).scalars().all()
    assert len(db_books) == 5
    titles = [b.title for b in db_books]
    assert "Harry Potter 1" in titles
    assert "Dune" in titles
    assert "Fundacion" in titles


def test_generic_and_cryptic_filename_detection():
    from app.services.metadata_extractor import is_generic_or_cryptic_filename

    assert is_generic_or_cryptic_filename("Capitulo 1.pdf") is True
    assert is_generic_or_cryptic_filename("Capitulo_1.epub") is True
    assert is_generic_or_cryptic_filename("chapter 12.pdf") is True
    assert is_generic_or_cryptic_filename("scan_001.pdf") is True
    assert is_generic_or_cryptic_filename("a8f3b29c.epub") is True
    assert is_generic_or_cryptic_filename("123456789.pdf") is True
    assert is_generic_or_cryptic_filename("doc.pdf") is True
    assert is_generic_or_cryptic_filename("bk.epub") is True

    # Nombres legítimos no deben ser detectados como crípticos
    assert is_generic_or_cryptic_filename("Cien Anos de Soledad.epub") is False
    assert is_generic_or_cryptic_filename("El Amor en los Tiempos del Colera.pdf") is False
    assert is_generic_or_cryptic_filename("Harry Potter y la Piedra Filosofal.epub") is False


@pytest.mark.asyncio
async def test_rename_book_handler_flow(test_session, monkeypatch):
    """Verifica que el comando /renombrar actualice el título y autor en la base de datos."""
    from app.bot.handlers import rename_book_handler
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_session_ctx():
        yield test_session

    monkeypatch.setattr("app.bot.handlers.AsyncSessionLocal", mock_session_ctx)

    user = User(id=88, nombre="Rename User")
    test_session.add(user)
    await test_session.commit()

    link = TelegramLink(
        id=88,
        user_id=88,
        chat_id=-100888888,
        chat_type="group_forum",
        chat_title="Forum Renombrar",
        bot_is_admin=True,
        forum_enabled=True
    )
    test_session.add(link)
    await test_session.commit()

    book = Book(
        user_id=user.id,
        telegram_link_id=link.id,
        telegram_message_id=5001,
        telegram_file_id="tg_file_rename_123",
        title="Capitulo 1",
        author="Desconocido",
        genre="General",
        file_format="pdf"
    )
    test_session.add(book)
    await test_session.commit()

    # Mock Telegram Update & Message
    target_msg = MagicMock()
    target_msg.message_id = 5001
    target_msg.document = MagicMock()
    target_msg.document.file_id = "tg_file_rename_123"

    mock_msg = MagicMock()
    mock_msg.reply_to_message = target_msg
    mock_msg.message_thread_id = None
    mock_msg.reply_text = AsyncMock()

    mock_chat = MagicMock()
    mock_chat.id = -100888888

    mock_update = MagicMock()
    mock_update.effective_message = mock_msg
    mock_update.effective_chat = mock_chat

    mock_context = MagicMock()
    mock_context.args = ["El", "Principito", "-", "Antoine", "de", "Saint-Exupéry", "-", "1943"]
    mock_context.bot = MagicMock()
    mock_context.bot.edit_message_caption = AsyncMock()

    await rename_book_handler(mock_update, mock_context)

    # Verificar que el libro fue actualizado en DB
    updated_book = (await test_session.execute(select(Book).where(Book.id == book.id))).scalar_one()
    assert updated_book.title == "El Principito"
    assert "Saint-Exupéry" in updated_book.author
    assert updated_book.publication_year == "1943"
    assert mock_msg.reply_text.called


@pytest.mark.asyncio
async def test_search_handler_and_pagination(test_session, monkeypatch):
    """Verifica la búsqueda de libros por título o autor (múltiples libros del mismo autor)."""
    from app.bot.handlers import search_handler, search_callback_handler
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_session_ctx():
        yield test_session

    monkeypatch.setattr("app.bot.handlers.AsyncSessionLocal", mock_session_ctx)

    user = User(id=99, nombre="Search User")
    test_session.add(user)
    await test_session.commit()

    link = TelegramLink(
        id=99,
        user_id=99,
        chat_id=-100999999,
        chat_type="group_forum",
        chat_title="Forum Search",
        bot_is_admin=True,
        forum_enabled=True
    )
    test_session.add(link)
    await test_session.commit()

    # Agregar 6 libros de Cecelia Ahern y 1 de Fitzgerald
    ahern_titles = [
        "Posdata: te amo",
        "Recuerdos prestados",
        "Si pudieras verme ahora",
        "Un lugar llamado aquí",
        "Un regalo del cielo",
        "Una cita con mi vida"
    ]
    for idx, t in enumerate(ahern_titles, start=1):
        b = Book(
            user_id=user.id,
            telegram_link_id=link.id,
            telegram_message_id=700 + idx,
            title=t,
            author="Cecelia Ahern",
            genre="Romance",
            file_format="epub",
            publication_year="2005"
        )
        test_session.add(b)

    gatsby = Book(
        user_id=user.id,
        telegram_link_id=link.id,
        telegram_message_id=750,
        title="El Gran Gatsby",
        author="Francis Scott Fitzgerald",
        genre="Romance",
        file_format="epub",
        publication_year="1925"
    )
    test_session.add(gatsby)
    await test_session.commit()

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    mock_msg = MagicMock()
    mock_msg.message_thread_id = None

    mock_chat = MagicMock()
    mock_chat.id = -100999999

    mock_update = MagicMock()
    mock_update.effective_message = mock_msg
    mock_update.effective_chat = mock_chat

    # 1. Búsqueda vacía -> Mensaje de ayuda
    mock_context_empty = MagicMock()
    mock_context_empty.args = []
    mock_context_empty.bot = mock_bot
    await search_handler(mock_update, mock_context_empty)
    assert mock_bot.send_message.called
    empty_call_text = mock_bot.send_message.call_args[1]["text"]
    assert "Búsqueda en la Biblioteca" in empty_call_text

    # 2. Búsqueda por autor con múltiples libros (Cecelia Ahern -> 6 libros)
    mock_context_ahern = MagicMock()
    mock_context_ahern.args = ["Cecelia", "Ahern"]
    mock_context_ahern.bot = mock_bot
    await search_handler(mock_update, mock_context_ahern)
    ahern_call_text = mock_bot.send_message.call_args[1]["text"]
    assert "6 libro(s) encontrado(s)" in ahern_call_text
    assert "Página 1 de 2" in ahern_call_text
    assert "Posdata: te amo" in ahern_call_text
    assert "Cecelia Ahern" in ahern_call_text

    # Verificar botón de paginación
    keyboard = mock_bot.send_message.call_args[1]["reply_markup"]
    btn_callbacks = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert any("search:" in cb and ":2" in cb for cb in btn_callbacks)

    # 3. Búsqueda por título (Gatsby)
    mock_context_title = MagicMock()
    mock_context_title.args = ["gatsby"]
    mock_context_title.bot = mock_bot
    await search_handler(mock_update, mock_context_title)
    title_call_text = mock_bot.send_message.call_args[1]["text"]
    assert "1 libro(s) encontrado(s)" in title_call_text
    assert "El Gran Gatsby" in title_call_text
    assert "1925" in title_call_text

    # 4. Búsqueda sin coincidencias
    mock_context_none = MagicMock()
    mock_context_none.args = ["NoExisteEsteLibroXYZ"]
    mock_context_none.bot = mock_bot
    await search_handler(mock_update, mock_context_none)
    none_call_text = mock_bot.send_message.call_args[1]["text"]
    assert "No se encontraron libros" in none_call_text


@pytest.mark.asyncio
async def test_external_book_search_and_download_flow(test_session, monkeypatch):
    """Verifica el flujo de búsqueda y descarga externa mediante /descargar y su callback."""
    from app.services.book_download_service import format_size, clean_author_name
    from app.bot.handlers import download_command_handler, download_callback_handler, _download_cache

    assert format_size(500 * 1024) == "500.0 KB"
    assert format_size(2 * 1024 * 1024) == "2.0 MB"
    assert clean_author_name("Cervantes Saavedra, Miguel de") == "Miguel de Cervantes Saavedra"
    assert clean_author_name(["Shakespeare, William"]) == "William Shakespeare"

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_session_ctx():
        yield test_session

    monkeypatch.setattr("app.bot.handlers.AsyncSessionLocal", mock_session_ctx)

    user = User(id=101, nombre="DL User")
    test_session.add(user)
    await test_session.commit()

    link = TelegramLink(
        id=101,
        user_id=101,
        chat_id=-100101101,
        chat_type="group_forum",
        chat_title="Forum DL",
        bot_is_admin=True,
        forum_enabled=True
    )
    test_session.add(link)
    await test_session.commit()

    mock_msg = MagicMock()
    mock_msg.message_thread_id = None
    mock_chat = MagicMock()
    mock_chat.id = -100101101

    mock_update = MagicMock()
    mock_update.effective_message = mock_msg
    mock_update.effective_chat = mock_chat

    mock_status_msg = MagicMock()
    mock_status_msg.edit_text = AsyncMock()

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(return_value=mock_status_msg)

    # 1. Comando sin argumentos -> Guía de ayuda
    mock_ctx_empty = MagicMock()
    mock_ctx_empty.args = []
    mock_ctx_empty.bot = mock_bot
    await download_command_handler(mock_update, mock_ctx_empty)
    assert mock_bot.send_message.called

    # 2. Comando con búsqueda -> Mockear search_external_books
    fake_results = [
        {
            "source": "Internet Archive",
            "title": "Don Quijote de la Mancha",
            "author": "Miguel de Cervantes",
            "year": "1605",
            "format": "epub",
            "filename": "quijote.epub",
            "size_str": "1.2 MB",
            "download_url": "https://archive.org/fake/quijote.epub"
        }
    ]

    async def mock_search_ext(q, max_results=5):
        return fake_results

    monkeypatch.setattr("app.services.book_download_service.search_external_books", mock_search_ext)

    mock_ctx_dl = MagicMock()
    mock_ctx_dl.args = ["Don", "Quijote"]
    mock_ctx_dl.bot = mock_bot

    await download_command_handler(mock_update, mock_ctx_dl)
    assert mock_status_msg.edit_text.called
    edit_text = mock_status_msg.edit_text.call_args[0][0]
    assert "Don Quijote de la Mancha" in edit_text
    assert "Internet Archive" in edit_text

    keyboard = mock_status_msg.edit_text.call_args[1]["reply_markup"]
    btn = keyboard.inline_keyboard[0][0]
    assert btn.callback_data.startswith("dl:")

    # 3. Callback de descarga: simular pulsación del botón
    dl_token = btn.callback_data.split(":")[1]

    async def mock_download_bytes(url):
        return b"fake-epub-bytes", "Don_Quijote.epub"

    async def mock_ingest(bot, session, link, chat_id, file_bytes, filename, original_meta=None):
        return {
            "status": "success",
            "title": "Don Quijote de la Mancha",
            "author": "Miguel de Cervantes",
            "genre": "Clásicos",
            "publication_year": "1605",
            "emoji": "🛡️",
            "file_format": "epub",
            "dest_link": "https://t.me/c/101101/999"
        }

    monkeypatch.setattr("app.services.book_download_service.download_book_bytes", mock_download_bytes)
    monkeypatch.setattr("app.services.book_download_service.ingest_downloaded_book", mock_ingest)

    mock_query = MagicMock()
    mock_query.data = f"dl:{dl_token}:0"
    mock_query.answer = AsyncMock()
    mock_query.edit_message_text = AsyncMock()

    mock_cb_update = MagicMock()
    mock_cb_update.callback_query = mock_query
    mock_cb_update.effective_chat = mock_chat

    mock_cb_context = MagicMock()
    mock_cb_context.bot = mock_bot

    await download_callback_handler(mock_cb_update, mock_cb_context)
    assert mock_query.edit_message_text.called
    final_text = mock_query.edit_message_text.call_args[0][0]
    assert "¡Libro descargado y archivado exitosamente!" in final_text
    assert "Don Quijote de la Mancha" in final_text
    assert "1605" in final_text


@pytest.mark.asyncio
async def test_libgen_search_and_download_resolution(monkeypatch):
    """Verifica el análisis de tamaño, búsqueda y resolución de descarga en dos pasos para Library Genesis."""
    from app.services.book_download_service import (
        parse_libgen_size,
        search_libgen,
        download_book_bytes
    )

    # 1. Validación de tamaños
    assert parse_libgen_size("12 MB") == 12 * 1024 * 1024
    assert parse_libgen_size("450 kB") == 450 * 1024
    assert parse_libgen_size("1.5 GB") == int(1.5 * 1024 * 1024 * 1024)
    assert parse_libgen_size("invalid") == 0

    # 2. Mock de búsqueda en LibGen
    fake_html = """
    <html>
    <table id="tablelibgen">
        <tr><th>Title</th><th>Author</th><th>Pub</th><th>Year</th><th>Lang</th><th>Pages</th><th>Size</th><th>Ext</th><th>Mirrors</th></tr>
        <tr>
            <td><a href="edition.php?id=123">Padre rico, padre pobre<i>edition info</i></a></td>
            <td>Kiyosaki, Robert T.</td>
            <td>Aguilar</td>
            <td>2021</td>
            <td>Spanish</td>
            <td>250</td>
            <td>1.2 MB</td>
            <td>epub</td>
            <td><a href="/ads.php?md5=3e8a08bd569a1c03849c6e991e92f704">Libgen</a></td>
        </tr>
    </table>
    </html>
    """

    class MockLibgenResponse:
        status_code = 200
        text = fake_html

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def get(self, url, params=None, headers=None):
            return MockLibgenResponse()

    monkeypatch.setattr("httpx.AsyncClient", MockAsyncClient)

    results = await search_libgen("Padre Rico", limit=2)
    assert len(results) == 1
    item = results[0]
    assert item["source"] == "Library Genesis"
    assert "Padre rico, padre pobre" in item["title"]
    assert item["author"] == "Robert T. Kiyosaki"
    assert item["year"] == "2021"
    assert item["format"] == "epub"
    assert item["size_bytes"] == int(1.2 * 1024 * 1024)
    assert "ads.php?md5=3e8a08bd569a1c03849c6e991e92f704" in item["download_url"]

    # 3. Test de resolución en dos pasos para download_book_bytes
    ads_html = """
    <html>
    <body>
        <a href="get.php?md5=3e8a08bd569a1c03849c6e991e92f704&key=TESTKEY123">GET</a>
    </body>
    </html>
    """

    class MockDownloadResponse:
        def __init__(self, url):
            self.url = url
            self.status_code = 200
            if "ads.php" in url:
                self.text = ads_html
                self.content = ads_html.encode()
                self.headers = {"content-type": "text/html"}
            else:
                self.text = ""
                self.content = b"PK\x03\x04fake_epub_content"
                self.headers = {"content-disposition": 'attachment; filename="padre_rico.epub"'}

    class MockTwoStepClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def get(self, url, params=None, headers=None):
            return MockDownloadResponse(url)

    monkeypatch.setattr("httpx.AsyncClient", MockTwoStepClient)

    file_bytes, filename = await download_book_bytes("https://libgen.li/ads.php?md5=3e8a08bd569a1c03849c6e991e92f704")
    assert file_bytes.startswith(b"PK\x03\x04")
    assert filename == "padre_rico.epub"


@pytest.mark.asyncio
async def test_series_description_and_info_handler(test_session, monkeypatch):
    """Verifica el formateo de descripción de sagas, continuaciones, libros anteriores/posteriores e info_handler."""
    from app.services.series_formatter import format_book_full_description
    from app.bot.handlers import info_handler
    from contextlib import asynccontextmanager

    # 1. Libros en la biblioteca
    b1 = Book(
        id=901,
        user_id=1,
        telegram_link_id=1,
        telegram_message_id=101,
        title="Harry Potter y la piedra filosofal",
        author="J.K. Rowling",
        genre="Fantasía",
        publication_year="1997",
        series_name="Harry Potter",
        series_type="Saga",
        series_order=1,
        series_total=7,
        has_sequel=True,
        previous_book=None,
        next_book="Harry Potter y la cámara secreta"
    )
    b2 = Book(
        id=902,
        user_id=1,
        telegram_link_id=1,
        telegram_message_id=102,
        title="Harry Potter y la cámara secreta",
        author="J.K. Rowling",
        genre="Fantasía",
        publication_year="1998",
        series_name="Harry Potter",
        series_type="Saga",
        series_order=2,
        series_total=7,
        has_sequel=True,
        previous_book="Harry Potter y la piedra filosofal",
        next_book="Harry Potter y el prisionero de Azkaban"
    )
    test_session.add_all([b1, b2])
    await test_session.commit()

    # 2. Formato de descripción de b2 (Libro 2 de la saga)
    desc = format_book_full_description(
        book=b2,
        chat_books=[b1, b2],
        clean_chat_id="123456",
        current_topic_name="Fantasía"
    )

    assert "Harry Potter y la cámara secreta" in desc
    assert "Saga:</b> Harry Potter (Libro 2 de 7)" in desc
    assert "Continuación:</b> Sí" in desc
    assert "Anterior:</b> <i>Harry Potter y la piedra filosofal</i>" in desc
    assert "✅ En biblioteca" in desc
    assert "https://t.me/c/123456/101" in desc
    assert "Siguiente:</b> <i>Harry Potter y el prisionero de Azkaban</i>" in desc
    assert "❌ No está en la biblioteca" in desc

    # 3. Formato de libro autoconclusivo
    b_auto = Book(
        id=903,
        user_id=1,
        telegram_link_id=1,
        title="Cien años de soledad",
        author="Gabriel García Márquez",
        genre="Novela",
        publication_year="1967",
        series_name=None,
        series_type="Autoconclusivo",
        has_sequel=False
    )
    desc_auto = format_book_full_description(
        book=b_auto,
        chat_books=[b_auto],
        clean_chat_id="123456"
    )
    assert "Obra:</b> Autoconclusiva" in desc_auto

    # 4. Probar comando /info
    @asynccontextmanager
    async def mock_session_ctx():
        yield test_session

    monkeypatch.setattr("app.bot.handlers.AsyncSessionLocal", mock_session_ctx)

    mock_msg = MagicMock()
    mock_msg.message_thread_id = None
    mock_msg.reply_to_message = None

    mock_chat = MagicMock()
    mock_chat.id = -100123456

    mock_update = MagicMock()
    mock_update.effective_message = mock_msg
    mock_update.effective_chat = mock_chat

    mock_context = MagicMock()
    mock_context.args = ["Harry", "Potter"]
    mock_context.bot = MagicMock()
    mock_context.bot.send_message = AsyncMock()

    link = TelegramLink(
        id=1,
        user_id=1,
        chat_id=-100123456,
        chat_type="group_forum",
        chat_title="Club de Lectura",
        bot_is_admin=True,
        forum_enabled=True
    )
    test_session.add(link)
    await test_session.commit()

    await info_handler(mock_update, mock_context)
    assert mock_context.bot.send_message.called
    sent_text = mock_context.bot.send_message.call_args[1]["text"]
    assert "Harry Potter" in sent_text
    assert "Saga" in sent_text


@pytest.mark.asyncio
async def test_register_reply_handler_with_custom_name_no_crash(test_session, monkeypatch):
    """Verifica que /registrar Título - Autor no intente mutar Message.caption ni lance AttributeError."""
    from app.bot.handlers import register_reply_handler
    from contextlib import asynccontextmanager
    from telegram import Message, Chat, Document
    from datetime import datetime, timezone

    @asynccontextmanager
    async def mock_session_ctx():
        yield test_session

    monkeypatch.setattr("app.bot.handlers.AsyncSessionLocal", mock_session_ctx)

    link = TelegramLink(
        id=701,
        user_id=1,
        chat_id=-100701701,
        chat_type="group_forum",
        chat_title="Forum Register",
        bot_is_admin=True,
        forum_enabled=True
    )
    test_session.add(link)
    await test_session.commit()

    captured_override = None

    async def mock_process_book(*args, **kwargs):
        nonlocal captured_override
        captured_override = kwargs.get("caption_override")
        return {
            "status": "success",
            "title": "Don Quijote",
            "author": "Miguel de Cervantes",
            "genre": "Clásicos",
            "emoji": "📜",
            "dest_link": "https://t.me/c/701701/999"
        }

    monkeypatch.setattr("app.bot.handlers.process_book_message", mock_process_book)

    chat = Chat(id=-100701701, type="supergroup")
    doc = Document(file_id="fid_real_1", file_unique_id="fuid_real_1", file_name="quijote.pdf")
    target_msg = Message(message_id=888, date=datetime.now(timezone.utc), chat=chat, document=doc)

    mock_cmd_msg = MagicMock()
    mock_cmd_msg.reply_to_message = target_msg
    mock_cmd_msg.message_thread_id = None
    mock_status_msg = MagicMock()
    mock_status_msg.edit_text = AsyncMock()
    mock_cmd_msg.reply_text = AsyncMock(return_value=mock_status_msg)

    mock_update = MagicMock()
    mock_update.effective_message = mock_cmd_msg
    mock_update.effective_chat = chat

    mock_context = MagicMock()
    mock_context.args = ["Don", "Quijote", "-", "Miguel", "de", "Cervantes"]
    mock_context.bot = MagicMock()

    # Ejecutar /registrar Don Quijote - Miguel de Cervantes
    await register_reply_handler(mock_update, mock_context)

    # Debe haber pasado el caption_override sin mutar target_msg
    assert captured_override == "Don Quijote - Miguel de Cervantes"
    assert mock_status_msg.edit_text.called
    edit_text = mock_status_msg.edit_text.call_args[0][0]
    assert "Don Quijote" in edit_text
    assert "Miguel de Cervantes" in edit_text


@pytest.mark.asyncio
async def test_rename_handler_null_file_ids_no_multiple_results_found(test_session, monkeypatch):
    """Verifica que /renombrar no falle con MultipleResultsFound cuando hay libros con telegram_file_id IS NULL."""
    from app.bot.handlers import rename_book_handler
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_session_ctx():
        yield test_session

    monkeypatch.setattr("app.bot.handlers.AsyncSessionLocal", mock_session_ctx)

    link = TelegramLink(
        id=702,
        user_id=1,
        chat_id=-100702702,
        chat_type="group_forum",
        chat_title="Forum Rename",
        bot_is_admin=True,
        forum_enabled=True
    )
    test_session.add(link)
    await test_session.commit()

    # Dos libros con telegram_file_id = None
    b1 = Book(user_id=1, title="Libro A", author="Autor A", genre="Terror", telegram_link_id=link.id, telegram_message_id=101, telegram_file_id=None)
    b2 = Book(user_id=1, title="Libro B", author="Autor B", genre="Terror", telegram_link_id=link.id, telegram_message_id=102, telegram_file_id=None)
    test_session.add_all([b1, b2])
    await test_session.commit()

    # Renombrar Libro B respondiendo a su mensaje 102 sin documento adjunto
    target_msg = MagicMock()
    target_msg.message_id = 102
    target_msg.document = None
    target_msg.text = None
    target_msg.caption = None

    cmd_msg = MagicMock()
    cmd_msg.reply_to_message = target_msg
    cmd_msg.reply_text = AsyncMock()

    mock_update = MagicMock()
    mock_update.effective_chat = MagicMock(id=-100702702, type="supergroup")
    mock_update.effective_message = cmd_msg

    mock_context = MagicMock()
    mock_context.args = ["Dracula", "-", "Bram", "Stoker"]

    await rename_book_handler(mock_update, mock_context)

    # Verificar que Libro B fue actualizado y no lanzó MultipleResultsFound
    await test_session.refresh(b2)
    assert b2.title == "Dracula"
    assert b2.author == "Bram Stoker"


@pytest.mark.asyncio
async def test_topic_index_chunking_large_topic(test_session, monkeypatch):
    """Verifica que /indice en un tema con más de 40 libros fragmente los mensajes para respetar el límite de 4096 caracteres."""
    from app.bot.handlers import topic_index_handler
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_session_ctx():
        yield test_session

    monkeypatch.setattr("app.bot.handlers.AsyncSessionLocal", mock_session_ctx)

    link = TelegramLink(
        id=703,
        user_id=1,
        chat_id=-100703703,
        chat_type="group_forum",
        chat_title="Forum Big Index",
        bot_is_admin=True,
        forum_enabled=True
    )
    test_session.add(link)
    await test_session.commit()

    topic = Topic(telegram_link_id=link.id, genre="Ciencia Ficcion", topic_id=333)
    test_session.add(topic)

    # 45 libros con títulos largos
    books = [
        Book(
            user_id=1,
            title=f"Cronicas del Espacio Interestelar y Mas Alla del Infinito Tomo {i}",
            author=f"Isaac Asimov y Arthur C. Clarke {i}",
            genre="Ciencia Ficcion",
            telegram_link_id=link.id,
            telegram_message_id=2000 + i,
            file_format="epub",
            publication_year="1990"
        )
        for i in range(45)
    ]
    test_session.add_all(books)
    await test_session.commit()

    mock_cmd_msg = MagicMock()
    mock_cmd_msg.message_thread_id = 333
    mock_update = MagicMock()
    mock_update.effective_chat = MagicMock(id=-100703703, type="supergroup")
    mock_update.effective_message = mock_cmd_msg

    sent_messages = []
    sent_keyboards = []

    async def mock_send_message(**kwargs):
        text = kwargs.get("text", "")
        # Validar límite estricto de Telegram
        assert len(text) <= 4096, f"Mensaje excede límite de Telegram ({len(text)} > 4096)"
        sent_messages.append(text)
        sent_keyboards.append(kwargs.get("reply_markup"))
        return MagicMock()

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(side_effect=mock_send_message)
    mock_context = MagicMock(bot=mock_bot)

    await topic_index_handler(mock_update, mock_context)

    # Ahora se envía un único mensaje paginado con botones inline interactivos para no saturar el grupo
    assert len(sent_messages) == 1
    assert "Página 1 de" in sent_messages[0]
    assert "45 obras disponibles" in sent_messages[0]
    assert sent_keyboards[0] is not None


@pytest.mark.asyncio
async def test_catalog_and_topics_in_private_chat(test_session, monkeypatch):
    """Verifica que /libros y /temas en chat privado devuelvan los libros asociados al usuario."""
    from app.bot.handlers import catalog_handler, topics_list_handler
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_session_ctx():
        yield test_session

    monkeypatch.setattr("app.bot.handlers.AsyncSessionLocal", mock_session_ctx)

    # Vínculo del usuario en chat privado
    priv_link = TelegramLink(
        id=704,
        user_id=777,
        chat_id=999777,  # Positivo = privado
        chat_type="private",
        chat_title="Usuario Privado",
        bot_is_admin=False,
        forum_enabled=False
    )
    test_session.add(priv_link)
    await test_session.commit()

    # Libros del usuario 777
    b1 = Book(user_id=777, title="El Hobbit", author="J.R.R. Tolkien", genre="Fantasia", file_format="epub")
    b2 = Book(user_id=777, title="Fundacion", author="Isaac Asimov", genre="Ciencia Ficcion", file_format="pdf")
    test_session.add_all([b1, b2])
    await test_session.commit()

    mock_msg = MagicMock()
    mock_msg.message_thread_id = None
    mock_chat = MagicMock(id=999777, type="private")

    mock_update = MagicMock()
    mock_update.effective_message = mock_msg
    mock_update.effective_chat = mock_chat

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    mock_context = MagicMock(bot=mock_bot, args=[])

    # 1. /libros en privado
    await catalog_handler(mock_update, mock_context)
    assert mock_bot.send_message.called
    cat_text = mock_bot.send_message.call_args[1]["text"]
    assert "El Hobbit" in cat_text
    assert "Fundacion" in cat_text

    # 2. /temas en privado
    mock_bot.send_message.reset_mock()
    await topics_list_handler(mock_update, mock_context)
    assert mock_bot.send_message.called
    topics_text = mock_bot.send_message.call_args[1]["text"]
    assert "Fantasia" in topics_text
    assert "Ciencia Ficcion" in topics_text


@pytest.mark.asyncio
async def test_reading_shelves_and_buddy_reads_api(client, test_session):
    """Verifica los endpoints REST de estantes de lectura y lecturas conjuntas."""
    user1 = User(id=801, nombre="Lector 1", email="lector1@test.com")
    user2 = User(id=802, nombre="Lector 2", email="lector2@test.com")
    test_session.add_all([user1, user2])
    await test_session.commit()

    book = Book(id=901, user_id=801, title="Dune", author="Frank Herbert", genre="Ciencia Ficcion")
    test_session.add(book)
    await test_session.commit()

    # 1. Actualizar estado a leyendo con 40% y favorito
    payload = {"status": "reading", "progress_percent": 40.0, "is_favorite": True}
    res_st = await client.put("/reading/status?user_id=801&book_id=901", json=payload)
    assert res_st.status_code == 200
    assert res_st.json()["status"] == "reading"
    assert res_st.json()["is_favorite"] is True
    assert res_st.json()["progress_percent"] == 40.0

    # 2. Consultar estantes de lectura
    res_sh = await client.get("/reading/shelves?user_id=801")
    assert res_sh.status_code == 200
    sh_data = res_sh.json()
    assert len(sh_data["reading"]) == 1
    assert len(sh_data["favorites"]) == 1
    assert sh_data["reading"][0]["book"]["title"] == "Dune"

    # 3. Iniciar lectura conjunta
    res_br = await client.post("/reading/buddy-reads?user_id=801", json={"book_id": 901, "title": "Lectura Conjunta Dune"})
    assert res_br.status_code == 200
    br_id = res_br.json()["id"]
    assert len(res_br.json()["members"]) == 1

    # 4. Segundo lector se une
    res_join = await client.post(f"/reading/buddy-reads/{br_id}/join?user_id=802")
    assert res_join.status_code == 200
    assert res_join.json()["user_id"] == 802

    # 5. Segundo lector avanza al 65%
    res_prog = await client.put(f"/reading/buddy-reads/{br_id}/progress?user_id=802&progress_percent=65.0")
    assert res_prog.status_code == 200
    assert res_prog.json()["progress_percent"] == 65.0

    # 6. Consultar co-lectores de Dune
    res_co = await client.get("/reading/co-readers/901")
    assert res_co.status_code == 200
    assert res_co.json()["count"] >= 2


@pytest.mark.asyncio
async def test_buddy_read_and_shelves_bot_handlers(test_session, monkeypatch):
    """Verifica los comandos de Telegram /leerjuntos, /mislibros y /progreso."""
    from app.bot.handlers import buddy_read_handler, my_books_handler, progress_command_handler
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_session_ctx():
        yield test_session

    monkeypatch.setattr("app.bot.handlers.AsyncSessionLocal", mock_session_ctx)

    link = TelegramLink(
        id=803,
        user_id=1,
        chat_id=-100803803,
        chat_type="group_forum",
        chat_title="Club Test",
        bot_is_admin=True,
        forum_enabled=True
    )
    test_session.add(link)
    await test_session.commit()

    book = Book(id=902, user_id=1, title="1984", author="George Orwell", genre="Distopia", telegram_link_id=803)
    test_session.add(book)
    await test_session.commit()

    chat = MagicMock(id=-100803803, type="supergroup")
    tg_user = MagicMock(id=555666, first_name="Carlos", username="carlos_reader")

    cmd_msg = MagicMock()
    cmd_msg.reply_to_message = None
    cmd_msg.message_thread_id = 10
    cmd_msg.reply_text = AsyncMock()

    mock_update = MagicMock(effective_chat=chat, effective_message=cmd_msg, effective_user=tg_user)
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
    mock_context = MagicMock(bot=mock_bot, args=["1984"])

    # 1. /leerjuntos 1984
    await buddy_read_handler(mock_update, mock_context)
    assert mock_bot.send_message.called
    sent_text = mock_bot.send_message.call_args[1]["text"]
    assert "LECTURA CONJUNTA EN CURSO" in sent_text
    assert "1984" in sent_text
    assert "Carlos" in sent_text

    # 2. /progreso 50%
    mock_context.args = ["50%"]
    await progress_command_handler(mock_update, mock_context)
    assert cmd_msg.reply_text.called
    prog_reply = cmd_msg.reply_text.call_args[0][0]
    assert "Avance registrado exitosamente" in prog_reply
    assert "50%" in prog_reply

    # 3. /mislibros
    mock_bot.send_message.reset_mock()
    mock_context.args = []
    await my_books_handler(mock_update, mock_context)
    assert mock_bot.send_message.called
    shelves_text = mock_bot.send_message.call_args[1]["text"]
    assert "Estantes de Lectura de Carlos" in shelves_text
    assert "1984" in shelves_text
    assert "50%" in shelves_text


@pytest.mark.asyncio
async def test_deduplication_and_lost_book_sentinel(test_session, monkeypatch):
    from app.services.book_sync_service import (
        deduplicate_library_for_chat,
        purge_deleted_books_for_chat,
        sync_all_library_for_chat
    )
    from app.bot.handlers import deduplicate_command_handler, lost_book_callback_handler
    from app.models.reading import ReadingState
    from telegram.error import BadRequest

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_session_ctx():
        yield test_session

    monkeypatch.setattr("app.bot.handlers.AsyncSessionLocal", mock_session_ctx)

    user = User(id=888, nombre="Dedup User")
    test_session.add(user)
    await test_session.commit()

    link = TelegramLink(
        id=888,
        user_id=888,
        chat_id=-100888999,
        chat_type="group_forum",
        chat_title="Dedup Chat",
        bot_is_admin=True,
        forum_enabled=True
    )
    test_session.add(link)
    await test_session.commit()

    # Create duplicate books: b1 (canonical) and b2 (duplicate)
    b1 = Book(id=801, user_id=888, title="Cien Años de Soledad", author="Gabriel García Márquez", telegram_link_id=888, telegram_message_id=501, genre="Realismo Mágico", file_format="epub")
    b2 = Book(id=802, user_id=888, title="cien anos de soledad", author="Gabriel Garcia Marquez", telegram_link_id=888, telegram_message_id=502, genre="General", file_format="epub")
    test_session.add_all([b1, b2])
    await test_session.commit()

    rs2 = ReadingState(user_id=888, book_id=802, progress_percent=40.0, status="reading")
    test_session.add(rs2)
    await test_session.commit()

    mock_bot = MagicMock()
    mock_bot.delete_message = AsyncMock(return_value=True)
    mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=9999))
    async def mock_edit_markup(chat_id, message_id, reply_markup=None):
        if message_id == 777:
            raise BadRequest("Message to edit not found")
        return True
    mock_bot.edit_message_reply_markup = AsyncMock(side_effect=mock_edit_markup)

    # Test deduplicate_library_for_chat
    res = await deduplicate_library_for_chat(mock_bot, test_session, link.id, link.chat_id)
    assert res["duplicates_removed"] == 1
    assert mock_bot.delete_message.called

    # Verify only b1 remains, and rs2 moved to b1
    remaining = (await test_session.execute(select(Book).where(Book.telegram_link_id == link.id))).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].id == 801

    rs_check = (await test_session.execute(select(ReadingState).where(ReadingState.book_id == 801))).scalar_one_or_none()
    assert rs_check is not None
    assert rs_check.progress_percent == 40.0

    # Test lost book alert (purge_deleted_books_for_chat with notify_lost=True)
    b_lost = Book(id=803, user_id=888, title="Rayuela", author="Julio Cortázar", telegram_link_id=888, telegram_message_id=777, genre="Ficción", file_format="epub")
    test_session.add(b_lost)
    await test_session.commit()

    lost_count = await purge_deleted_books_for_chat(mock_bot, test_session, link.id, link.chat_id, notify_lost=True)
    assert lost_count == 1
    assert mock_bot.send_message.called
    sent_alert = mock_bot.send_message.call_args[1]["text"]
    assert "Alerta de Biblioteca: Libro Extraviado" in sent_alert
    assert "Rayuela" in sent_alert

    # Verify b_lost has telegram_message_id = None
    b_lost_refreshed = (await test_session.execute(select(Book).where(Book.id == 803))).scalar_one()
    assert b_lost_refreshed.telegram_message_id is None

    # Test lost_book_callback_handler for discard (rec:del:803)
    mock_query_del = MagicMock()
    mock_query_del.data = "rec:del:803"
    mock_query_del.answer = AsyncMock()
    mock_query_del.edit_message_text = AsyncMock()
    mock_up_del = MagicMock(callback_query=mock_query_del, effective_chat=MagicMock(id=-100888999))

    await lost_book_callback_handler(mock_up_del, MagicMock(bot=mock_bot))
    assert mock_query_del.edit_message_text.called
    assert "descartado" in mock_query_del.edit_message_text.call_args[0][0]

    # Verify 803 is deleted from DB
    b_deleted = (await test_session.execute(select(Book).where(Book.id == 803))).scalar_one_or_none()
    assert b_deleted is None


@pytest.mark.asyncio
async def test_manga_chapter_packages_extraction_and_deduplication(test_session):
    """Verifica que los paquetes de capítulos de Manga/Manhwa conserven su rango y no se consideren duplicados erróneamente."""
    from app.services.ai_classifier import extract_manga_chapter_info, format_manga_title, fallback_parse_filename
    from app.services.topic_resolver import normalize_genre_slug

    # 1. Extracción de capítulos
    assert extract_manga_chapter_info("Solo Leveling 171-179.pdf") == "Cap. 171-179"
    assert extract_manga_chapter_info("[161-170] Solo Leveling.pdf") == "Cap. 161-170"
    assert extract_manga_chapter_info("Solo Leveling - Cap. 1-10.pdf") == "Cap. 1-10"
    assert extract_manga_chapter_info("Solo Leveling Tomo 3.pdf") == "Tomo 3"
    assert extract_manga_chapter_info("Cien Anos de Soledad.epub") is None

    # 2. Formateo de títulos
    t1 = format_manga_title("Solo Leveling", "Solo Leveling 171-179.pdf")
    t2 = format_manga_title("[161", "[161-170] Solo Leveling.pdf")
    assert "171-179" in t1
    assert "161-170" in t2
    assert "Solo Leveling" in t2

    # 3. Slugs diferentes para evitar falsos positivos de duplicado
    s1 = normalize_genre_slug(t1)
    s2 = normalize_genre_slug(t2)
    assert s1 != s2, f"Slugs colisionan: {s1} == {s2}"

    # 4. Fallback parser reconoce el paquete de capítulos
    meta1 = fallback_parse_filename("Solo Leveling 171-179.pdf")
    meta2 = fallback_parse_filename("[161-170] Solo Leveling.pdf")
    assert meta1["genre"] == "Manga/Manhwa/Manhua"
    assert meta2["genre"] == "Manga/Manhwa/Manhua"
    assert "171-179" in meta1["title"]
    assert "161-170" in meta2["title"]
    assert meta2["author"] != "170] Solo Leveling"









