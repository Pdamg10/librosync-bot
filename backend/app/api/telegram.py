from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.core.database import get_db
from app.models.telegram_link import TelegramLink
from app.schemas.telegram import TelegramLinkOut

router = APIRouter(prefix="/telegram", tags=["Telegram Links"])

@router.get("/links", response_model=List[TelegramLinkOut])
async def get_user_links(user_id: Optional[int] = Query(None), db: AsyncSession = Depends(get_db)):
    """Obtiene los chats de Telegram vinculados a la cuenta del usuario o comunidad."""
    stmt = select(TelegramLink)
    if user_id:
        stmt = stmt.where(or_(TelegramLink.user_id == user_id, TelegramLink.user_id == 1))
    res = await db.execute(stmt.order_by(TelegramLink.id.asc()))
    return res.scalars().all()

@router.delete("/links/{link_id}")
async def unlink_chat(link_id: int, db: AsyncSession = Depends(get_db)):
    """Desvincula un chat de Telegram."""
    stmt = select(TelegramLink).where(TelegramLink.id == link_id)
    res = await db.execute(stmt)
    link = res.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="Vínculo de Telegram no encontrado")

    await db.delete(link)
    await db.commit()
    return {"message": "Chat desvinculado exitosamente"}
