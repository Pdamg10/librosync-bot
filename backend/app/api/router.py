from fastapi import APIRouter
from app.api.auth import router as auth_router
from app.api.telegram import router as telegram_router
from app.api.library import router as library_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(telegram_router)
api_router.include_router(library_router)
