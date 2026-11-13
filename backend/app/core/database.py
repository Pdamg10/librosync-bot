import logging
import os
import sqlite3
from pathlib import Path
from typing import AsyncGenerator, Optional
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.core.config import settings

logger = logging.getLogger("librosync.database")

# In SQLite we need check_same_thread=False
connect_args = {}
is_sqlite = settings.DATABASE_URL.startswith("sqlite")
if is_sqlite:
    connect_args = {"check_same_thread": False}

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.SQL_ECHO,
    connect_args=connect_args,
    pool_pre_ping=True,
)

if is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        """Refuerza integridad y concurrencia de SQLite."""
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.execute("PRAGMA busy_timeout=5000;")
            # WAL no aplica a bases de datos en memoria usadas por tests.
            if ":memory:" not in settings.DATABASE_URL:
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
        finally:
            cursor.close()


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

Base = declarative_base()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def _seed_sqlite_catalog_if_empty(target_db_path: Optional[str] = None, seed_db_path: Optional[str] = None) -> bool:
    """
    Si la base de datos de destino en un contenedor efímero (ej. Hugging Face / Koyeb / Docker)
    está vacía o recién creada y existe una semilla del catálogo (/app/seed/librosync.db),
    restaura el catálogo inicial de forma atómica sin sobrescribir datos existentes.
    """
    db_file = target_db_path if target_db_path is not None else engine.url.database
    if not db_file or db_file == ":memory:":
        return False

    seed_candidate = seed_db_path or os.environ.get("SEED_DATABASE_PATH") or "/app/seed/librosync.db"
    seed_path = Path(seed_candidate)
    target_path = Path(db_file)

    if not seed_path.is_file():
        return False
    try:
        if target_path.exists() and seed_path.resolve() == target_path.resolve():
            return False
    except OSError:
        return False

    needs_seed = not target_path.exists() or target_path.stat().st_size == 0
    if not needs_seed:
        try:
            with sqlite3.connect(str(target_path)) as check_conn:
                cur = check_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='books'"
                )
                if cur.fetchone() is None:
                    needs_seed = True
                else:
                    book_count = check_conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
                    needs_seed = int(book_count or 0) == 0
        except Exception:
            needs_seed = False

    if not needs_seed:
        return False

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(seed_path)) as src_conn, sqlite3.connect(str(target_path)) as dst_conn:
            src_conn.backup(dst_conn)
        logger.info(f"📚 Catálogo inicial restaurado desde semilla ({seed_path}) hacia {target_path}.")
        return True
    except Exception as exc:
        logger.warning(f"No se pudo restaurar la semilla de base de datos desde {seed_path}: {exc}")
        return False


async def init_db():
    if is_sqlite:
        _seed_sqlite_catalog_if_empty()

    async with engine.begin() as conn:
        # Import models so they are registered with Base.metadata
        from app.models import user, telegram_link, topic, book, link_code, reading  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)

        from app.core.migrations import run_migrations
        await conn.run_sync(run_migrations)
