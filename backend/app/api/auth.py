import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.config import settings
from app.models.user import User
from app.models.link_code import LinkCode
from app.schemas.telegram import LinkCodeCreate, LinkCodeResponse

router = APIRouter(prefix="/auth/telegram", tags=["Auth & Linking"])

@router.post("/link-code", response_model=LinkCodeResponse)
async def generate_link_code(payload: LinkCodeCreate, db: AsyncSession = Depends(get_db)):
    """
    Genera un código efímero de vinculación y un deep-link de Telegram.
    El usuario abre este enlace desde el chat (grupo, canal o privado) que desea vincular.
    """
    # Verificar que el usuario exista o crearlo provisionalmente si es demo
    user_stmt = select(User).where(User.id == payload.user_id)
    res = await db.execute(user_stmt)
    user = res.scalar_one_or_none()

    if not user:
        # Para facilitar el desarrollo y onboarding inicial
        user = User(id=payload.user_id, nombre=f"Usuario {payload.user_id}")
        db.add(user)
        await db.commit()
        await db.refresh(user)

    code = secrets.token_hex(4).upper()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.LINK_CODE_TTL_MINUTES)

    link_code = LinkCode(
        code=code,
        user_id=user.id,
        expires_at=expires_at,
        used=False
    )
    db.add(link_code)
    await db.commit()

    deep_link = f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={code}"
    group_link = f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?startgroup={code}"

    return LinkCodeResponse(
        code=code,
        deep_link=deep_link,
        group_link=group_link,
        expires_at=expires_at
    )
