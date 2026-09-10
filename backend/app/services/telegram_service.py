import logging
from typing import Optional, Dict, Any
from telegram import Bot
from telegram.error import TelegramError, BadRequest

logger = logging.getLogger(__name__)

class ThreadNotFoundError(Exception):
    """Excepción cuando el topic/thread_id no existe o fue eliminado en Telegram."""
    pass

async def get_chat_and_bot_status(bot: Bot, chat_id: int) -> Dict[str, Any]:
    """
    Inspecciona el chat y determina permisos y configuración Forum.
    """
    try:
        chat = await bot.get_chat(chat_id)
        chat_type = chat.type
        chat_title = chat.title or (f"{chat.first_name or ''} {chat.last_name or ''}".strip()) or "Chat Privado"
        forum_enabled = getattr(chat, "is_forum", False) or False

        bot_is_admin = False
        can_manage_topics = False

        if chat_type in ["group", "supergroup", "channel"]:
            try:
                bot_member = await bot.get_chat_member(chat_id, bot.id)
                status = bot_member.status
                if status in ["administrator", "creator"]:
                    bot_is_admin = True
                    can_manage_topics = getattr(bot_member, "can_manage_topics", False) or False
            except TelegramError as e:
                logger.warning(f"No se pudo consultar estado de admin del bot en chat {chat_id}: {e}")

        return {
            "chat_title": chat_title,
            "chat_type": chat_type,
            "forum_enabled": forum_enabled,
            "bot_is_admin": bot_is_admin,
            "can_manage_topics": can_manage_topics,
        }
    except TelegramError as e:
        logger.error(f"Error al consultar get_chat en Telegram para chat {chat_id}: {e}")
        raise

async def send_book_document(
    bot: Bot,
    chat_id: int,
    document: Any,
    filename: Optional[str] = None,
    caption: Optional[str] = None,
    topic_id: Optional[int] = None
) -> Any:
    kwargs: Dict[str, Any] = {
        "chat_id": chat_id,
        "document": document,
        "caption": caption
    }
    if filename:
        kwargs["filename"] = filename
    if topic_id:
        kwargs["message_thread_id"] = topic_id

    try:
        return await bot.send_document(**kwargs)
    except BadRequest as e:
        if "message thread not found" in str(e).lower():
            raise ThreadNotFoundError(f"Thread {topic_id} no existe en Telegram.")
        raise

import asyncio
from telegram.error import TelegramError, BadRequest, RetryAfter

async def move_or_repost_to_topic(
    bot: Bot,
    chat_id: int,
    message_id: int,
    topic_id: int,
    delete_original: bool = True
) -> Optional[int]:
    """
    Copia un mensaje al Topic correspondiente y borra el original.
    Lanza ThreadNotFoundError si el topic fue eliminado en Telegram.
    Maneja automáticamente RetryAfter si Telegram frena por rate limits en envíos masivos.
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            new_msg = await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=chat_id,
                message_id=message_id,
                message_thread_id=topic_id
            )
            if delete_original:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=message_id)
                except RetryAfter as del_rate_err:
                    await asyncio.sleep(del_rate_err.retry_after + 0.5)
                    try:
                        await bot.delete_message(chat_id=chat_id, message_id=message_id)
                    except Exception:
                        pass
                except TelegramError as del_err:
                    logger.warning(f"No se pudo borrar el mensaje original {message_id} en chat {chat_id}: {del_err}")
            return new_msg.message_id

        except RetryAfter as rate_err:
            wait_time = rate_err.retry_after + 1.0
            logger.warning(f"Rate limit de Telegram alcanzado al mover mensaje. Esperando {wait_time}s (intento {attempt+1}/{max_retries})...")
            await asyncio.sleep(wait_time)
            continue
        except BadRequest as e:
            err_msg = str(e).lower()
            if "message thread not found" in err_msg or "thread_id_invalid" in err_msg:
                logger.warning(f"Thread {topic_id} no existe en Telegram: {e}")
                raise ThreadNotFoundError(f"El topic {topic_id} fue eliminado en Telegram.")
            logger.error(f"Error BadRequest al copiar mensaje {message_id} al topic {topic_id}: {e}")
            return None
        except TelegramError as e:
            logger.error(f"Error al reubicar mensaje {message_id} al topic {topic_id}: {e}")
            return None
    return None
