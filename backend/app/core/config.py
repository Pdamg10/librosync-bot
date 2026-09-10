from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

from pathlib import Path

# Buscar .env en backend/ o en root
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"

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
    API_PORT: int = 8000
    API_HOST: str = "0.0.0.0"
    
    # Linking
    LINK_CODE_TTL_MINUTES: int = 15
    STORAGE_DIR: str = str(BASE_DIR / "storage")

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
