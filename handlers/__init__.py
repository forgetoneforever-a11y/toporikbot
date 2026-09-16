from aiogram import Router

from .base import router as base_router
from .subscriber import router as subscriber_router
from .admin import router as admin_router
from .text_fallback import router as text_fallback_router

router = Router()
router.include_router(base_router)
router.include_router(subscriber_router)
router.include_router(admin_router)
router.include_router(text_fallback_router)