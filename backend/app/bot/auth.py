"""Autorización para operaciones sensibles del bot."""
from __future__ import annotations

import logging
from typing import Optional

from telegram import Chat, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app.core.config import settings

logger = logging.getLogger(__name__)

_ADMIN_STATUSES = {"administrator", "creator", "owner"}


def _status_value(member) -> str:
    status = getattr(member, "status", "")
    return str(getattr(status, "value", status)).lower()


async def is_chat_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat: Optional[Chat] = None,
    user_id: Optional[int] = None,
) -> bool:
    """Devuelve True si el usuario es administrador del chat o está en la allowlist.

    En chats privados el dueño del chat siempre puede administrar su biblioteca.
    En grupos y canales se consulta a Telegram: no se confía en texto ni en
    callbacks enviados por el cliente.
    """
    chat = chat or update.effective_chat
    user = update.effective_user
    uid = user_id if user_id is not None else (user.id if user else None)

    if not chat or uid is None:
        return False

    if uid in settings.admin_telegram_ids:
        return True

    if chat.type == "private":
        return True

    try:
        member = await context.bot.get_chat_member(chat.id, uid)
    except TelegramError as exc:
        logger.warning("No se pudo verificar admin en chat %s: %s", chat.id, exc)
        return False
    except Exception as exc:  # pragma: no cover - defensivo ante mocks/red
        logger.warning("Error verificando admin en chat %s: %s", chat.id, exc)
        return False

    return _status_value(member) in _ADMIN_STATUSES


async def require_chat_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    action: str = "esta acción",
) -> bool:
    """Comprueba permisos y responde al usuario si no está autorizado."""
    if await is_chat_admin(update, context):
        return True

    text = (
        "⛔ <b>Permiso denegado.</b>\n"
        f"Solo los administradores del grupo pueden ejecutar {action}."
    )
    query = update.callback_query
    try:
        if query:
            await query.answer("⛔ Solo administradores del grupo", show_alert=True)
        else:
            message = update.effective_message
            chat = update.effective_chat
            if message and chat:
                thread_id = getattr(message, "message_thread_id", None)
                await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=thread_id,
                    text=text,
                    parse_mode="HTML",
                )
    except Exception:
        pass
    return False


async def require_group_admin_for_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: Optional[int],
) -> bool:
    """Exige que quien vincula un grupo sea administrador de ese grupo."""
    chat = update.effective_chat
    if not chat:
        return False
    if chat.type == "private":
        return True
    return await is_chat_admin(update, context, chat=chat, user_id=user_id)
