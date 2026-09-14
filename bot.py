import asyncio
import datetime
import logging
import os
import sqlite3
import uuid
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
)
import yt_dlp

# Настрой токен твоего бота здесь или через переменные окружения
TOKEN = os.getenv("BOT_TOKEN", "ТВОЙ_ТОКЕН_БОТА")
ADMIN_ID = 123456789  # Укажи свой Telegram ID для доступа к админке

logging.basicConfig(level=logging.INFO)
router = Router()

# ================= DATABASE =================
conn = sqlite3.connect("bot_database.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    repeat_mode INTEGER DEFAULT 1,
    language TEXT DEFAULT 'ru',
    premium_until TIMESTAMP DEFAULT NULL,
    bonus_videos INTEGER DEFAULT 0
)
"""
)
conn.commit()

# Безопасное добавление новых колонок для существующих баз
for col_def in [
    ("premium_until", "TIMESTAMP DEFAULT NULL"),
    ("bonus_videos", "INTEGER DEFAULT 0"),
]:
    try:
        cursor.execute(f"ALTER TABLE users ADD COLUMN {col_def[0]} {col_def[1]}")
        conn.commit()
    except sqlite3.OperationalError:
        pass


def get_user_lang(user_id: int) -> str:
    cursor.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else "ru"


# ================= TEXTS & LOCALIZATION =================
LANG_TEXTS = {
    "ru": {
        "welcome": (
            "👋 <b>Привет!</b> Я бот для скачивания медиа и управления контентом.\n\n"
            "Отправь мне ссылку на видео/аудио, и я скачаю её для тебя!"
        ),
        "btn_kids": "🧸 Категория 1",
        "btn_porno": "🔞 Категория 2",
        "btn_random": "🎲 Случайное видео",
        "btn_premium": "⭐ Премиум и Звезды",
        "btn_help": "❓ Помощь",
        "btn_contact": "📞 Поддержка",
        "btn_admin": "🛠 Админ-панель",
        "premium_menu": (
            "⭐ <b>Telegram Stars & Премиум-доступ</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "Поддержи проект и получи расширенные возможности:\n\n"
            "🎁 <b>10 ⭐</b> — Пакет из 10 видео\n"
            "🔥 <b>100 ⭐</b> — Пакет из 100 видео\n"
            "👑 <b>1000 ⭐</b> — <b>VIP-подписка на 1 месяц</b> (доступ ко всем категориям и видео без ограничений!)\n\n"
            "Выбери тариф ниже:"
        ),
        "help_text": "📖 <b>Справка:</b>\nПросто отправь ссылку на поддерживаемый ресурс, и бот пришлет файл.",
        "contact_admin": "✍️ Написать администратору можно через @admin_username",
        "lang_changed": "🌍 Язык успешно изменен на русский!",
    },
    "en": {
        "welcome": (
            "👋 <b>Hello!</b> I am a media downloader bot.\n\n"
            "Send me a link to a video/audio, and I will download it for you!"
        ),
        "btn_kids": "🧸 Category 1",
        "btn_porno": "🔞 Category 2",
        "btn_random": "🎲 Random Video",
        "btn_premium": "⭐ Premium & Stars",
        "btn_help": "❓ Help",
        "btn_contact": "📞 Support",
        "btn_admin": "🛠 Admin Panel",
        "premium_menu": (
            "⭐ <b>Telegram Stars & Premium Access</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "Support the project and get advanced features:\n\n"
            "🎁 <b>10 ⭐</b> — 10 videos pack\n"
            "🔥 <b>100 ⭐</b> — 100 videos pack\n"
            "👑 <b>1000 ⭐</b> — <b>VIP Subscription for 1 month</b> (unlimited access!)\n\n"
            "Choose a plan below:"
        ),
        "help_text": "📖 <b>Help:</b>\nJust send a link to a resource, and the bot will send you the file.",
        "contact_admin": "✍️ Contact admin at @admin_username",
        "lang_changed": "🌍 Language successfully changed to English!",
    },
}


def get_user_keyboard(is_admin: bool, lang: str = "ru"):
    t = LANG_TEXTS.get(lang, LANG_TEXTS["ru"])
    keyboard = [
        [
            InlineKeyboardButton(text=t["btn_kids"], callback_data="watch_kids"),
            InlineKeyboardButton(text=t["btn_porno"], callback_data="watch_porno"),
        ],
        [InlineKeyboardButton(text=t["btn_random"], callback_data="random_video")],
        [InlineKeyboardButton(text=t["btn_premium"], callback_data="premium_shop")],
        [
            InlineKeyboardButton(text=t["btn_help"], callback_data="help_menu"),
            InlineKeyboardButton(text=t["btn_contact"], callback_data="contact_admin"),
        ],
        [InlineKeyboardButton(text="🌍 Change Language", callback_data="change_language")],
    ]
    if is_admin:
        keyboard.append(
            [InlineKeyboardButton(text=t["btn_admin"], callback_data="admin_panel")]
        )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ================= HANDLERS: START & MENU =================
@router.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (user_id, username),
    )
    conn.commit()

    lang = get_user_lang(user_id)
    t = LANG_TEXTS[lang]
    is_admin = (user_id == ADMIN_ID)

    await message.answer(
        t["welcome"],
        reply_markup=get_user_keyboard(is_admin, lang),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    t = LANG_TEXTS[lang]
    is_admin = (callback.from_user.id == ADMIN_ID)

    await callback.message.edit_text(
        t["welcome"],
        reply_markup=get_user_keyboard(is_admin, lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "help_menu")
async def cb_help(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    t = LANG_TEXTS[lang]
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]]
    )
    await callback.message.edit_text(t["help_text"], reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "contact_admin")
async def cb_contact(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    t = LANG_TEXTS[lang]
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]]
    )
    await callback.message.edit_text(t["contact_admin"], reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "change_language")
async def cb_change_language(callback: CallbackQuery):
    current_lang = get_user_lang(callback.from_user.id)
    new_lang = "en" if current_lang == "ru" else "ru"
    
    cursor.execute("UPDATE users SET language = ? WHERE user_id = ?", (new_lang, callback.from_user.id))
    conn.commit()
    
    t = LANG_TEXTS[new_lang]
    await callback.answer(t["lang_changed"], show_alert=True)
    
    is_admin = (callback.from_user.id == ADMIN_ID)
    await callback.message.edit_text(
        t["welcome"],
        reply_markup=get_user_keyboard(is_admin, new_lang),
        parse_mode="HTML",
    )


# ================= PREMIUM & TELEGRAM STARS SHOP =================
@router.callback_query(F.data == "premium_shop")
async def premium_shop_handler(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    t = LANG_TEXTS[lang]
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 10 звезд (10 видео)", callback_data="buy_stars_10")],
            [InlineKeyboardButton(text="🔥 100 звезд (100 видео)", callback_data="buy_stars_100")],
            [InlineKeyboardButton(text="👑 1000 звезд (Подписка на месяц)", callback_data="buy_stars_1000")],
            [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu")]
        ]
    )
    await callback.message.edit_text(t["premium_menu"], reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.message(Command("premium"))
async def cmd_premium(message: Message):
    lang = get_user_lang(message.from_user.id)
    t = LANG_TEXTS[lang]
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 10 звезд (10 видео)", callback_data="buy_stars_10")],
            [InlineKeyboardButton(text="🔥 100 звезд (100 видео)", callback_data="buy_stars_100")],
            [InlineKeyboardButton(text="👑 1000 звезд (Подписка на месяц)", callback_data="buy_stars_1000")],
            [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu")]
        ]
    )
    await message.answer(t["premium_menu"], reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data.startswith("buy_stars_"))
async def process_buy_stars(callback: CallbackQuery):
    amount = int(callback.data.split("_")[2])
    
    if amount == 10:
        title = "Пакет видео (10 шт.)"
        description = "Дает право просмотреть 10 дополнительных видео."
        payload = "star_pack_10"
    elif amount == 100:
        title = "Большой пакет видео (100 шт.)"
        description = "Дает право просмотреть 100 дополнительных видео."
        payload = "star_pack_100"
    elif amount == 1000:
        title = "VIP-подписка на 1 месяц"
        description = "Полный безлимитный доступ ко всем материалам бота на 30 дней."
        payload = "star_sub_1000"
    else:
        await callback.answer("❌ Неизвестный тариф", show_alert=True)
        return

    prices = [LabeledPrice(label="Telegram Stars", amount=amount)]
    
    await callback.message.bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=title,
        description=description,
        payload=payload,
        currency="XTR",  # Валюта Telegram Stars
        prices=prices,
        provider_token="" # Для цифровых товаров и звезд provider_token всегда пустой
    )
    await callback.answer()


@router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: CallbackQuery):
    await pre_checkout_query.bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message):
    payment = message.successful_payment
    payload = payment.invoice_payload
    user_id = message.from_user.id
    
    if payload == "star_pack_10":
        cursor.execute("UPDATE users SET bonus_videos = bonus_videos + 10 WHERE user_id = ?", (user_id,))
        conn.commit()
        await message.answer("🎉 <b>Оплата прошла успешно!</b>\nТебе добавлено +10 видео к просмотру.", parse_mode="HTML")
        
    elif payload == "star_pack_100":
        cursor.execute("UPDATE users SET bonus_videos = bonus_videos + 100 WHERE user_id = ?", (user_id,))
        conn.commit()
        await message.answer("🎉 <b>Оплата прошла успешно!</b>\nТебе добавлено +100 видео к просмотру.", parse_mode="HTML")
        
    elif payload == "star_sub_1000":
        expire_date = datetime.datetime.now() + datetime.timedelta(days=30)
        cursor.execute("UPDATE users SET premium_until = ? WHERE user_id = ?", (expire_date, user_id))
        conn.commit()
        await message.answer("👑 <b>Поздравляем с покупкой VIP-подписки!</b>\nДоступ ко всем материалам активирован на 30 дней.", parse_mode="HTML")


# ================= YT-DLP DOWNLOADER LOGIC =================
@router.message(F.text.startswith("http"))
async def download_media_link(message: Message):
    url = message.text.strip()
    processing_msg = await message.answer("⏳ Скачиваю медиа, подождите...")

    file_id = str(uuid.uuid4())
    output_template = f"{file_id}.%(ext)s"

    ydl_opts = {
        "outtmpl": output_template,
        "format": "best[filesize<50M]/best", # Ограничение под лимиты телеграма (~50МБ)
        "noplaylist": True,
    }

    downloaded_file = None
    try:
        def run_dl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info)

        downloaded_file = await asyncio.to_thread(run_dl)

        if os.path.exists(downloaded_file):
            file_size = os.path.getsize(downloaded_file) / (1024 * 1024)
            if file_size > 50:
                await processing_msg.edit_text("❌ Файл слишком большой (больше 50 МБ), Telegram не разрешает отправить.")
            else:
                await message.answer_video(video=open(downloaded_file, "rb"))
                await processing_msg.delete()
        else:
            await processing_msg.edit_text("❌ Не удалось найти скачанный файл.")
            
    except Exception as e:
        logging.error(f"Download error: {e}")
        await processing_msg.edit_text(f"❌ Ошибка при скачивании: {str(e)}")
    finally:
        if downloaded_file and os.path.exists(downloaded_file):
            try:
                os.remove(downloaded_file)
            except:
                pass


# ================= MAIN FUNCTION =================
async def main():
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    # Регистрация команд в меню бота
    from aiogram.types import BotCommand
    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="premium", description="⭐ Премиум и Звезды"),
    ])

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
