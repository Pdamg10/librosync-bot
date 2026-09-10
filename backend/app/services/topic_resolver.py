import logging
import re
import unicodedata
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from telegram import Bot
from telegram.error import TelegramError
from app.models.topic import Topic
from app.models.telegram_link import TelegramLink

logger = logging.getLogger(__name__)

def normalize_genre_slug(genre: str) -> str:
    """Normaliza una cadena eliminando acentos, espacios y signos para búsqueda canónica."""
    if not genre:
        return "general"
    nfkd = unicodedata.normalize('NFKD', genre).encode('ASCII', 'ignore').decode('utf-8')
    return re.sub(r'[^a-zA-Z0-9]', '', nfkd).lower()

async def delete_topic_by_thread_id(session: AsyncSession, telegram_link_id: int, topic_id: int):
    """Elimina un topic de la base de datos cuando Telegram reporta que fue eliminado."""
    stmt = select(Topic).where(
        Topic.telegram_link_id == telegram_link_id,
        Topic.topic_id == topic_id
    )
    res = await session.execute(stmt)
    topic = res.scalar_one_or_none()
    if topic:
        logger.info(f"Purgando topic zombie '{topic.genre}' (thread {topic_id}) de la base de datos.")
        await session.delete(topic)
        await session.commit()

async def resolve_or_create_topic(
    session: AsyncSession,
    bot: Bot,
    telegram_link: TelegramLink,
    genre: Optional[str] = "General"
) -> Optional[int]:
    """
    Resuelve el topic_id para un género dado:
    1. Si no es un supergrupo con Forum activado, retorna None.
    2. Búsqueda exacta en BD por género.
    3. Búsqueda difusa/normalizada en BD (ej: 'darkromance' coincide con 'Dark Romance').
    4. Si no existe coincidencia, crea el topic en Telegram con un nombre limpio y lo guarda en BD.
    """
    clean_genre = (genre or "General").strip().title()

    if not telegram_link.forum_enabled:
        logger.info(f"Chat {telegram_link.chat_id} no tiene modo Forum activado.")
        return None

    # 1. Búsqueda exacta en BD
    stmt = select(Topic).where(
        Topic.telegram_link_id == telegram_link.id,
        Topic.genre == clean_genre
    )
    result = await session.execute(stmt)
    existing_topic = result.scalar_one_or_none()

    if existing_topic:
        logger.info(f"Topic exacto en BD: '{clean_genre}' -> id {existing_topic.topic_id}")
        return existing_topic.topic_id

    # 2. Búsqueda normalizada / slug (para evitar duplicados por espacios o tildes)
    target_slug = normalize_genre_slug(clean_genre)
    all_topics_stmt = select(Topic).where(Topic.telegram_link_id == telegram_link.id)
    all_res = await session.execute(all_topics_stmt)
    all_topics = all_res.scalars().all()

    for t in all_topics:
        if normalize_genre_slug(t.genre) == target_slug:
            logger.info(f"Topic coincidente por normalización: '{clean_genre}' == '{t.genre}' -> id {t.topic_id}")
            return t.topic_id

    # 3. No existe -> Crear nuevo Topic en Telegram
    try:
        logger.info(f"Creando nuevo Forum Topic en Telegram: Chat {telegram_link.chat_id}, Género '{clean_genre}'")
        created_topic = await bot.create_forum_topic(
            chat_id=telegram_link.chat_id,
            name=clean_genre
        )
        topic_id = created_topic.message_thread_id

        # Guardar en BD
        new_topic = Topic(
            telegram_link_id=telegram_link.id,
            genre=clean_genre,
            topic_id=topic_id
        )
        session.add(new_topic)
        await session.commit()
        await session.refresh(new_topic)

        logger.info(f"Topic creado exitosamente: '{clean_genre}' -> thread {topic_id}")
        return topic_id

    except TelegramError as e:
        logger.error(f"Error al crear topic en Telegram para chat {telegram_link.chat_id}: {e}")
        return None
