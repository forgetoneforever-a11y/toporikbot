from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
import html

from config import ADMIN_IDS, VIDEO_CACHE, VIDEO_CACHE_BY_CATEGORY, SUPPORTED_LANGS
from database import db
from keyboards import get_user_keyboard, get_language_keyboard, get_repeat_keyboard
from texts import get_texts

router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message):
    await db.ensure_user(message.from_user.id, message.from_user.username)
    lang = await db.get_user_lang(message.from_user.id)
    texts = get_texts(lang)
    
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer(texts["welcome"], reply_markup=get_user_keyboard(is_admin, lang), parse_mode="HTML")

@router.callback_query(F.data == "main_menu_fixed")
async def main_menu_callback(callback: CallbackQuery):
    lang = await db.get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    is_admin = callback.from_user.id in ADMIN_IDS
    
    await callback.message.edit_text(texts["welcome"], reply_markup=get_user_keyboard(is_admin, lang), parse_mode="HTML")
    await callback.answer()

@router.message(Command("language"))
@router.callback_query(F.data == "change_language")
async def language_handler(event: Message | CallbackQuery):
    user_id = event.from_user.id
    lang = await db.get_user_lang(user_id)
    texts = get_texts(lang)
    
    markup = get_language_keyboard()
    if isinstance(event, Message):
        await event.answer(texts["choose_lang"], reply_markup=markup)
    else:
        await event.message.edit_text(texts["choose_lang"], reply_markup=markup)
        await event.answer()

@router.callback_query(F.data.startswith("set_lang_"))
async def set_lang_callback(callback: CallbackQuery):
    lang = callback.data.split("_")[2]
    if lang in SUPPORTED_LANGS:
        await db.update_user_lang(callback.from_user.id, lang)
        texts = get_texts(lang)
        await callback.answer(texts["lang_changed"], show_alert=True)
        is_admin = callback.from_user.id in ADMIN_IDS
        await callback.message.edit_text(texts["welcome"], reply_markup=get_user_keyboard(is_admin, lang), parse_mode="HTML")
    else:
        await callback.answer("❌ Invalid language", show_alert=True)

@router.message(Command("setting"))
async def cmd_setting(message: Message):
    user_id = message.from_user.id
    lang = await db.get_user_lang(user_id)
    texts = get_texts(lang)
    repeat_mode = await db.get_repeat_mode(user_id)
    
    await message.answer(texts["settings_title"], reply_markup=get_repeat_keyboard(repeat_mode, lang), parse_mode="HTML")

@router.callback_query(F.data == "toggle_repeat")
async def toggle_repeat_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    current_mode = await db.get_repeat_mode(user_id)
    new_mode = 0 if current_mode == 1 else 1
    await db.update_repeat_mode(user_id, new_mode)
    
    lang = await db.get_user_lang(user_id)
    texts = get_texts(lang)
    
    await callback.message.edit_reply_markup(reply_markup=get_repeat_keyboard(new_mode, lang))
    await callback.answer(texts["settings_updated"])

@router.message(Command("help"))
@router.callback_query(F.data == "help_menu")
async def help_handler(event: Message | CallbackQuery):
    user_id = event.from_user.id
    lang = await db.get_user_lang(user_id)
    texts = get_texts(lang)
    
    if isinstance(event, Message):
        await event.answer(texts["help_text"], parse_mode="HTML")
    else:
        await event.message.edit_text(texts["help_text"], reply_markup=get_user_keyboard(user_id in ADMIN_IDS, lang), parse_mode="HTML")
        await callback_answer_safe(event)

async def callback_answer_safe(callback: CallbackQuery):
    try:
        await callback.answer()
    except Exception:
        pass