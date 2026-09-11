from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict
from app.schemas.book import BookOut

class ReadingStateBase(BaseModel):
    status: Optional[str] = "to_read"  # 'reading' | 'finished' | 'to_read' | 'abandoned'
    is_favorite: Optional[bool] = False
    progress_percent: Optional[float] = 0.0
    current_page: Optional[int] = None
    total_pages: Optional[int] = None
    notes: Optional[str] = None

class ReadingStateUpdate(BaseModel):
    status: Optional[str] = None
    is_favorite: Optional[bool] = None
    progress_percent: Optional[float] = None
    current_page: Optional[int] = None
    total_pages: Optional[int] = None
    notes: Optional[str] = None

class ReadingStateOut(ReadingStateBase):
    id: int
    user_id: int
    book_id: int
    created_at: datetime
    updated_at: datetime
    book: Optional[BookOut] = None

    model_config = ConfigDict(from_attributes=True)


class ShelfSummaryOut(BaseModel):
    reading: List[ReadingStateOut]
    finished: List[ReadingStateOut]
    to_read: List[ReadingStateOut]
    favorites: List[ReadingStateOut]
    total_tracked: int


class BuddyReadMemberOut(BaseModel):
    id: int
    user_id: int
    telegram_user_id: Optional[int] = None
    telegram_username: Optional[str] = None
    telegram_name: Optional[str] = None
    progress_percent: float
    current_page: Optional[int] = None
    status: str
    joined_at: datetime
    last_progress_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BuddyReadCreate(BaseModel):
    book_id: int
    telegram_link_id: Optional[int] = None
    title: Optional[str] = None
    target_date: Optional[datetime] = None


class BuddyReadOut(BaseModel):
    id: int
    book_id: int
    telegram_link_id: Optional[int] = None
    creator_user_id: int
    title: Optional[str] = None
    status: str
    target_date: Optional[datetime] = None
    created_at: datetime
    book: Optional[BookOut] = None
    members: List[BuddyReadMemberOut] = []

    model_config = ConfigDict(from_attributes=True)
