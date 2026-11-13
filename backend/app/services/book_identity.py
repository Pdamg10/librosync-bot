"""Identidad canónica de una obra para deduplicar sin perder autores distintos.

Una biblioteca puede tener el mismo título con autores diferentes (remakes,
antologías, ediciones atribuidas) y varios libros distintos del mismo autor.
El identificador incluye siempre autor y formato.
"""
from __future__ import annotations

from typing import Optional

from app.services.topic_resolver import normalize_genre_slug

_PLACEHOLDER_AUTHORS = {
    "",
    "desconocido",
    "desconocida",
    "unknown",
    "sin autor",
    "anonimo",
    "anónimo",
}


def normalize_author_key(author: Optional[str]) -> str:
    raw = (author or "").strip()
    if raw.lower() in _PLACEHOLDER_AUTHORS:
        return ""
    return normalize_genre_slug(raw)


def normalize_format_key(file_format: Optional[str]) -> str:
    return (file_format or "epub").strip().lower().lstrip(".") or "epub"


def book_identity_key(
    title: Optional[str],
    author: Optional[str],
    file_format: Optional[str],
) -> tuple[str, str, str]:
    """Clave estable título + autor + formato."""
    return (
        normalize_genre_slug(title or ""),
        normalize_author_key(author),
        normalize_format_key(file_format),
    )
