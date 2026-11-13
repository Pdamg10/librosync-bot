"""Configuración de logging con redacción de secretos.

Telegram incluye el token del bot en la ruta de sus peticiones y Gemini incluye
la API key en la query string. Nunca debemos volcar esos valores en consola,
archivos de log o en el reporte de excepciones.
"""
import logging
import re

from app.core.config import settings

_BOT_TOKEN_RE = re.compile(r"(?:bot)?\d{5,}:[A-Za-z0-9_-]{10,}")
_QUERY_SECRET_RE = re.compile(
    r"([?&](?:key|token|access_token|api_key|apikey|bot_token)=)[^&\s\"']+",
    re.IGNORECASE,
)
_AUTH_HEADER_RE = re.compile(
    r"(Authorization\s*[:=]\s*)(?:(?:Bearer|Basic|Token)\s+)?[^\s,;]+",
    re.IGNORECASE,
)


def redact_sensitive(text: str) -> str:
    if not text:
        return text
    text = _BOT_TOKEN_RE.sub("bot<redacted>", text)
    text = _QUERY_SECRET_RE.sub(r"\1<redacted>", text)
    text = _AUTH_HEADER_RE.sub(r"\1<redacted>", text)
    return text


class RedactingFormatter(logging.Formatter):
    """Formatter que redacta el mensaje final, incluido el traceback."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_sensitive(super().format(record))


_NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "telegram",
    "telegram.ext",
    "sqlalchemy.engine",
)


def configure_logging() -> None:
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(
        RedactingFormatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Estas librerías registran URLs completas (con token) en nivel INFO.
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    if settings.DEBUG:
        logging.getLogger("librosync").debug("DEBUG habilitado")
