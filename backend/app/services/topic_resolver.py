import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from telegram import Bot
from telegram.error import TelegramError
from app.models.topic import Topic
from app.models.telegram_link import TelegramLink

logger = logging.getLogger(__name__)

async def resolve_or_create_topic(
    session: AsyncSession,
    bot: Bot,
    telegram_link: TelegramLink,
    genre: Optional[str] = "General"
) -> Optional[int]:
    """
    Resuelve el topic_id (message_thread_id) para un género dado en un supergrupo.
    1. Si el chat no tiene Forum activado, retorna None.
    2. Busca en la caché de BD si el topic para ese género ya fue creado.
    3. Si no existe, invoca create_forum_topic en Telegram y persiste el mapping.
    """
    clean_genre = (genre or "General").strip().title()

    # Si no es un supergrupo con forum, no hay topics
    if not telegram_link.forum_enabled:
        logger.info(f"Chat {telegram_link.chat_id} no tiene modo Forum activado. No se usan topics.")
        return None

    # 1. Buscar en BD
    stmt = select(Topic).where(
        Topic.telegram_link_id == telegram_link.id,
        Topic.genre == clean_genre
    )
    result = await session.execute(stmt)
    existing_topic = result.scalar_one_or_none()

    if existing_topic:
        logger.info(f"Topic encontrado en caché BD: '{clean_genre}' -> id {existing_topic.topic_id}")
        return existing_topic.topic_id

    # 2. No existe -> Crear en Telegram
    try:
        logger.info(f"Creando Forum Topic en Telegram: Chat {telegram_link.chat_id}, Género '{clean_genre}'")
        created_topic = await bot.create_forum_topic(
            chat_id=telegram_link.chat_id,
            name=clean_genre
        )
        topic_id = created_topic.message_thread_id

        # 3. Guardar en BD
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
        # Si falló (por ejemplo por falta de permisos de 'Manage Topics'), devolvemos None
        return None
