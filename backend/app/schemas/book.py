from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class BookBase(BaseModel):
    title: str
    author: Optional[str] = "Desconocido"
    genre: Optional[str] = "General"
    cover_url: Optional[str] = None
    file_format: Optional[str] = "pdf"

class BookCreate(BookBase):
    user_id: int
    source: str = "app"
    telegram_link_id: Optional[int] = None
    telegram_message_id: Optional[int] = None
    telegram_file_id: Optional[str] = None
    file_unique_id: Optional[str] = None

class BookUpdate(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    genre: Optional[str] = None
    reading_progress: Optional[float] = None

class BookOut(BookBase):
    id: int
    user_id: int
    source: str
    telegram_link_id: Optional[int] = None
    telegram_message_id: Optional[int] = None
    telegram_file_id: Optional[str] = None
    file_unique_id: Optional[str] = None
    uploaded_at: datetime
    reading_progress: float

    model_config = ConfigDict(from_attributes=True)
