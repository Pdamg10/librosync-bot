from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class LinkCodeCreate(BaseModel):
    user_id: int

class LinkCodeResponse(BaseModel):
    code: str
    deep_link: str
    group_link: Optional[str] = None
    expires_at: datetime

class TelegramLinkOut(BaseModel):
    id: int
    user_id: int
    chat_id: int
    chat_type: str
    chat_title: Optional[str] = None
    bot_is_admin: bool
    forum_enabled: bool
    linked_at: datetime

    model_config = ConfigDict(from_attributes=True)

class TopicOut(BaseModel):
    id: int
    telegram_link_id: int
    genre: str
    topic_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
