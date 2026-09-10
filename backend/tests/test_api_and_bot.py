import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from unittest.mock import AsyncMock, MagicMock

from app.core.database import Base, get_db
from app.main import app
from app.models.user import User
from app.models.telegram_link import TelegramLink
from app.models.topic import Topic
from app.models.book import Book
from app.services.topic_resolver import resolve_or_create_topic

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
    # Generar código para user_id = 1
    response = await client.post("/auth/telegram/link-code", json={"user_id": 1})
    assert response.status_code == 200
    data = response.json()
    assert "code" in data
    assert "deep_link" in data
    assert data["code"] in data["deep_link"]


@pytest.mark.asyncio
async def test_topic_resolver_caching(test_session):
    # Crear usuario y link de prueba
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

    # Mock del bot de Telegram
    mock_bot = MagicMock()
    mock_topic_result = MagicMock()
    mock_topic_result.message_thread_id = 42
    mock_bot.create_forum_topic = AsyncMock(return_value=mock_topic_result)

    # 1ra llamada: debe llamar a bot.create_forum_topic
    thread_id = await resolve_or_create_topic(test_session, mock_bot, link, "Ciencia Ficción")
    assert thread_id == 42
    assert mock_bot.create_forum_topic.call_count == 1

    # 2da llamada con el mismo género: debe venir de caché (DB), NO llamar de nuevo al bot
    cached_thread_id = await resolve_or_create_topic(test_session, mock_bot, link, "Ciencia Ficción")
    assert cached_thread_id == 42
    assert mock_bot.create_forum_topic.call_count == 1  # No se incrementó


@pytest.mark.asyncio
async def test_library_crud(client, test_session):
    # Crear usuario
    user = User(id=1, nombre="Test User")
    test_session.add(user)
    await test_session.commit()

    # Insertar libro directo
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

    # Listar biblioteca
    res = await client.get("/library?user_id=1")
    assert res.status_code == 200
    books = res.json()
    assert len(books) == 1
    assert books[0]["title"] == "Dune"

    # Filtrar por género existente
    res_filtered = await client.get("/library?user_id=1&genre=Ciencia Ficción")
    assert len(res_filtered.json()) == 1

    # Filtrar por género inexistente
    res_empty = await client.get("/library?user_id=1&genre=Romance")
    assert len(res_empty.json()) == 0

    # Actualizar progreso
    patch_res = await client.patch(f"/library/{book.id}", json={"reading_progress": 0.45})
    assert patch_res.status_code == 200
    assert patch_res.json()["reading_progress"] == 0.45

    # Borrar libro
    del_res = await client.delete(f"/library/{book.id}")
    assert del_res.status_code == 200

    # Verificar que ya no está
    get_res = await client.get(f"/library/{book.id}")
    assert get_res.status_code == 404
