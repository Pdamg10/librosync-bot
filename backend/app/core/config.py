import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AliasChoices

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
    DEBUG: bool = True
    SECRET_KEY: str = "librosync-super-secret-key"
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_BOT_USERNAME: str = "Griffintor_bot"
    
    # AI Classifier (Google Gemini)
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"

    # Database
    DATABASE_URL: str = f"sqlite+aiosqlite:///{BASE_DIR}/librosync.db"
    
    # API
    API_PORT: int = Field(default_factory=_resolve_default_port, validation_alias=AliasChoices("PORT", "API_PORT"))
    API_HOST: str = "0.0.0.0"
    KEEP_ALIVE_URL: Optional[str] = Field(default_factory=_resolve_keep_alive_url, validation_alias=AliasChoices("KEEP_ALIVE_URL", "RENDER_EXTERNAL_URL"))
    
    # Linking
    LINK_CODE_TTL_MINUTES: int = 15
    STORAGE_DIR: str = str(BASE_DIR / "storage")

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
