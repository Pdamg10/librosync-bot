from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, BigInteger, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base

def utc_now():
    return datetime.now(timezone.utc)

class TelegramLink(Base):
    __tablename__ = "telegram_links"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    chat_id = Column(BigInteger, unique=True, index=True, nullable=False)
    chat_type = Column(String(50), nullable=False)  # group_forum | channel | private
    chat_title = Column(String(255), nullable=True)
    bot_is_admin = Column(Boolean, default=False)
    forum_enabled = Column(Boolean, default=False)
    linked_at = Column(DateTime, default=utc_now)

    # Relationships
    user = relationship("User", back_populates="telegram_links")
    topics = relationship("Topic", back_populates="telegram_link", cascade="all, delete-orphan")
    books = relationship("Book", back_populates="telegram_link")
