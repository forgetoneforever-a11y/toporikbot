from aiogram import Router, F
from aiogram.types import Message

from database import db

router = Router()

@router.message(F.text)
async def text_fallback_handler(message: Message):
    lang = await db.get_user_lang(message.from_user.id)
    # Можно добавить мягкую подсказку или игнорировать
    await message.answer("❓ Используйте меню или команды для взаимодействия с ботом.")