from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base

def utc_now():
    return datetime.now(timezone.utc)

class Book(Base):
    __tablename__ = "books"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False, index=True)
    author = Column(String(255), default="Desconocido", index=True)
    genre = Column(String(100), default="General")
    cover_url = Column(String(1024), nullable=True)
    source = Column(String(50), default="telegram")  # 'app' | 'telegram'
    telegram_link_id = Column(Integer, ForeignKey("telegram_links.id", ondelete="SET NULL"), nullable=True, index=True)
    telegram_message_id = Column(Integer, nullable=True)
    telegram_topic_id = Column(Integer, nullable=True)
    telegram_file_id = Column(String(255), nullable=True)
    file_unique_id = Column(String(100), index=True, nullable=True)
    file_format = Column(String(20), default="pdf")  # 'pdf' | 'epub' | 'mobi'
    publication_year = Column(String(50), nullable=True)  # Año o fecha de salida original
    series_name = Column(String(255), nullable=True)  # Nombre de la saga o trilogía
    series_type = Column(String(50), nullable=True)  # 'Saga' | 'Trilogía' | 'Bilogía' | 'Serie' | 'Autoconclusivo'
    series_order = Column(Integer, nullable=True)  # Orden o número del libro (ej: 1, 2)
    series_total = Column(Integer, nullable=True)  # Total de libros en la saga si se conoce
    previous_book = Column(String(255), nullable=True)  # Título del libro anterior
    next_book = Column(String(255), nullable=True)  # Título del libro siguiente
    has_sequel = Column(Boolean, nullable=True)  # True si tiene continuación, False si es libro final o autoconclusivo
    uploaded_at = Column(DateTime, default=utc_now, index=True)
    reading_progress = Column(Float, default=0.0)

    # Relationships
    user = relationship("User", back_populates="books")
    telegram_link = relationship("TelegramLink", back_populates="books")
