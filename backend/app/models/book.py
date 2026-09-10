from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base

def utc_now():
    return datetime.now(timezone.utc)

class Book(Base):
    __tablename__ = "books"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    author = Column(String(255), default="Desconocido")
    genre = Column(String(100), default="General")
    cover_url = Column(String(1024), nullable=True)
    source = Column(String(50), default="telegram")  # 'app' | 'telegram'
    telegram_link_id = Column(Integer, ForeignKey("telegram_links.id", ondelete="SET NULL"), nullable=True)
    telegram_message_id = Column(Integer, nullable=True)
    telegram_file_id = Column(String(255), nullable=True)
    file_format = Column(String(20), default="pdf")  # 'pdf' | 'epub' | 'mobi'
    uploaded_at = Column(DateTime, default=utc_now)
    reading_progress = Column(Float, default=0.0)

    # Relationships
    user = relationship("User", back_populates="books")
    telegram_link = relationship("TelegramLink", back_populates="books")
