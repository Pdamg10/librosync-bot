from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class BookBase(BaseModel):
    title: str
    author: Optional[str] = "Desconocido"
    genre: Optional[str] = "General"
    cover_url: Optional[str] = None
    file_format: Optional[str] = "pdf"
    publication_year: Optional[str] = None
    series_name: Optional[str] = None
    series_type: Optional[str] = None
    series_order: Optional[int] = None
    series_total: Optional[int] = None
    previous_book: Optional[str] = None
    next_book: Optional[str] = None
    has_sequel: Optional[bool] = None

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
    publication_year: Optional[str] = None
    series_name: Optional[str] = None
    series_type: Optional[str] = None
    series_order: Optional[int] = None
    series_total: Optional[int] = None
    previous_book: Optional[str] = None
    next_book: Optional[str] = None
    has_sequel: Optional[bool] = None
    reading_progress: Optional[float] = None

class BookOut(BookBase):
    id: int
    user_id: int
    source: str
    telegram_link_id: Optional[int] = None
    telegram_message_id: Optional[int] = None
    telegram_file_id: Optional[str] = None
    file_unique_id: Optional[str] = None
    publication_year: Optional[str] = None
    uploaded_at: datetime
    reading_progress: float

    model_config = ConfigDict(from_attributes=True)
