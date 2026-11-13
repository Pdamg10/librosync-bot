from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base

def utc_now():
    return datetime.now(timezone.utc)

class Topic(Base):
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True, index=True)
    telegram_link_id = Column(Integer, ForeignKey("telegram_links.id", ondelete="CASCADE"), nullable=False, index=True)
    genre = Column(String(100), nullable=False)
    topic_id = Column(Integer, nullable=False)  # message_thread_id from Telegram
    created_at = Column(DateTime, default=utc_now)

    # Relationships
    telegram_link = relationship("TelegramLink", back_populates="topics")

    __table_args__ = (
        UniqueConstraint("telegram_link_id", "genre", name="uq_link_genre"),
    )
