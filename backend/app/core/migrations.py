"""Migraciones ligeras y versionadas para SQLite.

El proyecto no usa Alembic todavía. Este runner aplica cambios idempotentes y
registra la versión en `schema_migrations`, de modo que una actualización no
dependa de recordar ALTER TABLE manuales.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Dict, List, Tuple

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)

MigrationFn = Callable[[object], None]


def _add_book_columns(conn) -> None:
    inspector = inspect(conn)
    if "books" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("books")}
    additions: List[Tuple[str, str]] = [
        ("publication_year", "VARCHAR(50)"),
        ("series_name", "VARCHAR(255)"),
        ("series_type", "VARCHAR(50)"),
        ("series_order", "INTEGER"),
        ("series_total", "INTEGER"),
        ("previous_book", "VARCHAR(255)"),
        ("next_book", "VARCHAR(255)"),
        ("has_sequel", "BOOLEAN"),
        ("telegram_topic_id", "INTEGER"),
    ]
    for name, sql_type in additions:
        if name not in columns:
            conn.execute(text(f"ALTER TABLE books ADD COLUMN {name} {sql_type};"))


def _create_indexes(conn) -> None:
    statements = [
        "CREATE INDEX IF NOT EXISTS ix_books_telegram_link_id ON books (telegram_link_id);",
        "CREATE INDEX IF NOT EXISTS ix_books_user_id ON books (user_id);",
        "CREATE INDEX IF NOT EXISTS ix_books_title ON books (title);",
        "CREATE INDEX IF NOT EXISTS ix_books_author ON books (author);",
        "CREATE INDEX IF NOT EXISTS ix_books_uploaded_at ON books (uploaded_at);",
        "CREATE INDEX IF NOT EXISTS ix_books_link_message ON books (telegram_link_id, telegram_message_id);",
        "CREATE INDEX IF NOT EXISTS ix_books_link_unique_file ON books (telegram_link_id, file_unique_id);",
        "CREATE INDEX IF NOT EXISTS ix_topics_telegram_link_id ON topics (telegram_link_id);",
        "CREATE INDEX IF NOT EXISTS ix_telegram_links_user_id ON telegram_links (user_id);",
        "CREATE INDEX IF NOT EXISTS ix_link_codes_user_id ON link_codes (user_id);",
    ]
    for statement in statements:
        conn.execute(text(statement))


# Versión -> (nombre, función). Añadir nuevas migraciones al final, nunca
# modificar una ya publicada.
MIGRATIONS: Dict[int, Tuple[str, MigrationFn]] = {
    1: ("add_book_metadata_columns", _add_book_columns),
    2: ("create_performance_indexes", _create_indexes),
}


def run_migrations(sync_conn) -> None:
    sync_conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, "
            "name VARCHAR(255) NOT NULL, "
            "applied_at VARCHAR(64) NOT NULL"
            ");"
        )
    )

    applied = {
        row[0]
        for row in sync_conn.execute(text("SELECT version FROM schema_migrations;"))
    }

    for version in sorted(MIGRATIONS):
        if version in applied:
            continue
        name, migration = MIGRATIONS[version]
        logger.info("Aplicando migración %s (%s)...", version, name)
        migration(sync_conn)
        sync_conn.execute(
            text(
                "INSERT INTO schema_migrations (version, name, applied_at) "
                "VALUES (:version, :name, :applied_at);"
            ),
            {
                "version": version,
                "name": name,
                "applied_at": datetime.now(timezone.utc).isoformat(),
            },
        )
