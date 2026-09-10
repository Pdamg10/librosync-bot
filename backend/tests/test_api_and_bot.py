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
        assert res["genre"] == "Fantasía"
        assert mock_sleep.called

