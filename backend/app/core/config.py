import os
import secrets
from pathlib import Path
from typing import Optional, Set
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AliasChoices, field_validator

# Buscar .env en backend/ o en root
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"


def _resolve_default_port() -> int:
    port_env = os.environ.get("PORT") or os.environ.get("API_PORT")
    if port_env:
        try:
            return int(port_env)
        except ValueError:
            pass
    if "SPACE_ID" in os.environ:
        return 7860
    return 8000


def _resolve_keep_alive_url() -> Optional[str]:
    url = os.environ.get("KEEP_ALIVE_URL") or os.environ.get("RENDER_EXTERNAL_URL")
    if url:
        return url
    space_host = os.environ.get("SPACE_HOST")
    if space_host:
        return f"https://{space_host}"
    return None


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    # Solo se usa para firmas internas; en producción debe definirse en el entorno.
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(48))

    # Telegram
    # Se valida al arrancar el bot, no al importar el módulo, para permitir
    # ejecutar herramientas de CI/lint sin credenciales reales.
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_BOT_USERNAME: str = "Griffintor_bot"
    ADMIN_TELEGRAM_IDS: str = ""

    # AI Classifier (Google Gemini)
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"

    # Database
    DATABASE_URL: str = Field(
        default_factory=lambda: (
            f"sqlite+aiosqlite:///{BASE_DIR.parent}/librosync.db"
            if (BASE_DIR.parent / "librosync.db").exists()
            else f"sqlite+aiosqlite:///{BASE_DIR}/librosync.db"
        )
    )
    SQL_ECHO: bool = False

    # API
    API_PORT: int = Field(default_factory=_resolve_default_port, validation_alias=AliasChoices("PORT", "API_PORT"))
    API_HOST: str = "0.0.0.0"
    KEEP_ALIVE_URL: Optional[str] = Field(default_factory=_resolve_keep_alive_url, validation_alias=AliasChoices("KEEP_ALIVE_URL", "RENDER_EXTERNAL_URL"))

    # Logging / red
    LOG_LEVEL: str = "INFO"
    # Workaround de red específico de un ISP. Desactivado por defecto.
    ENABLE_NETWORK_PATCH: bool = False

    # Linking
    LINK_CODE_TTL_MINUTES: int = 15
    STORAGE_DIR: str = str(BASE_DIR / "storage")

    # Límites operativos
    MAX_DOWNLOAD_SIZE_MB: int = 48
    DOWNLOAD_TOTAL_TIMEOUT_SECONDS: int = 90
    DOWNLOAD_PROGRESS_INTERVAL_SECONDS: int = 8
    DOWNLOAD_CACHE_TTL_SECONDS: int = 7200
    SEARCH_RATE_LIMIT: int = 20
    SEARCH_RATE_WINDOW_SECONDS: int = 300
    DOWNLOAD_RATE_LIMIT: int = 10
    DOWNLOAD_RATE_WINDOW_SECONDS: int = 300

    @field_validator("LOG_LEVEL")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        level = (value or "INFO").strip().upper()
        return level if level in allowed else "INFO"

    @property
    def admin_telegram_ids(self) -> Set[int]:
        """IDs de Telegram con permisos globales de mantenimiento."""
        result: Set[int] = set()
        for raw in (self.ADMIN_TELEGRAM_IDS or "").split(","):
            raw = raw.strip()
            if raw.lstrip("-").isdigit():
                result.add(int(raw))
        return result

    @property
    def is_production(self) -> bool:
        return (self.ENVIRONMENT or "").strip().lower() in {"production", "prod"}

    @property
    def max_download_size_bytes(self) -> int:
        return max(1, int(self.MAX_DOWNLOAD_SIZE_MB)) * 1024 * 1024

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
