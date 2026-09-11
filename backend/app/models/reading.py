from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, BigInteger, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base

def utc_now():
    return datetime.now(timezone.utc)

class ReadingState(Base):
    """
    Estado de lectura individual por usuario y libro.
    Permite gestionar estantes personales: Favoritos, Leyendo, Terminados, Por leer.
    """
    __tablename__ = "reading_states"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    book_id = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # 'reading' | 'finished' | 'to_read' | 'abandoned'
    status = Column(String(50), default="to_read", nullable=False)
    is_favorite = Column(Boolean, default=False, nullable=False)
    progress_percent = Column(Float, default=0.0, nullable=False)
    current_page = Column(Integer, nullable=True)
    total_pages = Column(Integer, nullable=True)
    notes = Column(String(1000), nullable=True)
    
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        UniqueConstraint("user_id", "book_id", name="uq_user_book_reading_state"),
    )

    user = relationship("User", backref="reading_states")
    book = relationship("Book", backref="reading_states")


class BuddyRead(Base):
    """
    Lectura Conjunta compartida entre múltiples usuarios en un grupo o foro.
    Mínimo 2 personas, sin límite superior de participantes.
    """
    __tablename__ = "buddy_reads"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    telegram_link_id = Column(Integer, ForeignKey("telegram_links.id", ondelete="CASCADE"), nullable=True, index=True)
    creator_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    title = Column(String(255), nullable=True)
    # 'active' | 'completed' | 'cancelled'
    status = Column(String(50), default="active", nullable=False)
    target_date = Column(DateTime, nullable=True)
    
    telegram_message_id = Column(Integer, nullable=True)
    telegram_thread_id = Column(Integer, nullable=True)
    
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    book = relationship("Book", backref="buddy_reads")
    telegram_link = relationship("TelegramLink", backref="buddy_reads")
    creator = relationship("User", foreign_keys=[creator_user_id])
    members = relationship("BuddyReadMember", back_populates="buddy_read", cascade="all, delete-orphan")


class BuddyReadMember(Base):
    """
    Participante individual en una Lectura Conjunta.
    Rastrea el progreso personal en porcentaje y página.
    """
    __tablename__ = "buddy_read_members"

    id = Column(Integer, primary_key=True, index=True)
    buddy_read_id = Column(Integer, ForeignKey("buddy_reads.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    telegram_user_id = Column(BigInteger, nullable=True)
    telegram_username = Column(String(255), nullable=True)
    telegram_name = Column(String(255), nullable=True)
    
    progress_percent = Column(Float, default=0.0, nullable=False)
    current_page = Column(Integer, nullable=True)
    # 'reading' | 'finished' | 'paused'
    status = Column(String(50), default="reading", nullable=False)
    
    joined_at = Column(DateTime, default=utc_now)
    last_progress_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        UniqueConstraint("buddy_read_id", "user_id", name="uq_buddy_read_member"),
    )

    buddy_read = relationship("BuddyRead", back_populates="members")
    user = relationship("User", backref="buddy_read_memberships")
