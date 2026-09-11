from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.core.config import settings

# In SQLite we need check_same_thread=False
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    connect_args=connect_args
)

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

async def init_db():
    async with engine.begin() as conn:
        # Import models so they are registered with Base.metadata
        from app.models import user, telegram_link, topic, book, link_code, reading
        await conn.run_sync(Base.metadata.create_all)

        def _migrate_columns(sync_conn):
            from sqlalchemy import inspect, text
            inspector = inspect(sync_conn)
            tables = inspector.get_table_names()
            if "books" in tables:
                cols = [c["name"] for c in inspector.get_columns("books")]
                if "publication_year" not in cols:
                    sync_conn.execute(text("ALTER TABLE books ADD COLUMN publication_year VARCHAR(50);"))
                if "series_name" not in cols:
                    sync_conn.execute(text("ALTER TABLE books ADD COLUMN series_name VARCHAR(255);"))
                if "series_type" not in cols:
                    sync_conn.execute(text("ALTER TABLE books ADD COLUMN series_type VARCHAR(50);"))
                if "series_order" not in cols:
                    sync_conn.execute(text("ALTER TABLE books ADD COLUMN series_order INTEGER;"))
                if "series_total" not in cols:
                    sync_conn.execute(text("ALTER TABLE books ADD COLUMN series_total INTEGER;"))
                if "previous_book" not in cols:
                    sync_conn.execute(text("ALTER TABLE books ADD COLUMN previous_book VARCHAR(255);"))
                if "next_book" not in cols:
                    sync_conn.execute(text("ALTER TABLE books ADD COLUMN next_book VARCHAR(255);"))
                if "has_sequel" not in cols:
                    sync_conn.execute(text("ALTER TABLE books ADD COLUMN has_sequel BOOLEAN;"))

        await conn.run_sync(_migrate_columns)
