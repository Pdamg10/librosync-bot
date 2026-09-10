from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, BigInteger, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base

def utc_now():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=True)
    nombre = Column(String(255), nullable=False)
    telegram_user_id = Column(BigInteger, unique=True, index=True, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    # Relationships
    telegram_links = relationship("TelegramLink", back_populates="user", cascade="all, delete-orphan")
    books = relationship("Book", back_populates="user", cascade="all, delete-orphan")
    link_codes = relationship("LinkCode", back_populates="user", cascade="all, delete-orphan")
