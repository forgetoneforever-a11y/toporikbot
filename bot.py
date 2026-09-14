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

# Настрой токен твоего бота здесь или через переменные окружения на Render
TOKEN = os.getenv("BOT_TOKEN", "ТВОЙ_ТОКЕН_БОТА")
ADMIN_ID = 123456789  # Укажи свой Telegram ID для доступа к админке

logging.basicConfig(level=logging.INFO)
router = Router()

# ================= FSM ДЛЯ АДМИНКИ =================
class AdminStates(StatesGroup):
    waiting_for_broadcast = State()

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
    bonus_videos INTEGER DEFAULT 0,
    watched_videos INTEGER DEFAULT 0
)
"""
)
conn.commit()

# Безопасное добавление новых колонок для существующих баз
for col_def in [
    ("premium_until", "TIMESTAMP DEFAULT NULL"),
    ("bonus_videos", "INTEGER DEFAULT 0"),
    ("watched_videos", "INTEGER DEFAULT 0"),
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
        "btn_profile": "👤 Личный кабинет",
        "btn_premium": "⭐ Премиум и Магазин",
        "btn_help": "❓ Помощь",
        "btn_contact": "📞 Поддержка",
        "btn_admin": "🛠 Админ-панель",
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
        "btn_profile": "👤 Profile",
        "btn_premium": "⭐ Premium & Shop",
        "btn_help": "❓ Help",
        "btn_contact": "📞 Support",
        "btn_admin": "🛠 Admin Panel",
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
        [
            InlineKeyboardButton(text=t["btn_profile"], callback_data="user_profile"),
            InlineKeyboardButton(text=t["btn_premium"], callback_data="premium_shop"),
        ],
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


# ================= STUB HANDLERS FOR CATEGORIES =================
@router.callback_query(F.data.in_({"watch_kids", "watch_porno", "random_video"}))
async def cb_stub_categories(callback: CallbackQuery):
    await callback.answer("🚧 Этот раздел находится в разработке!", show_alert=True)


# ================= PROFILE (ЛИЧНЫЙ КАБИНЕТ) =================
@router.callback_query(F.data == "user_profile")
async def user_profile_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT watched_videos, bonus_videos, premium_until FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if row:
        watched, bonus, premium_until = row
    else:
        watched, bonus, premium_until = 0, 0, None

    if premium_until:
        if isinstance(premium_until, str):
            try:
                premium_dt = datetime.datetime.fromisoformat(premium_until)
            except ValueError:
                premium_dt = None
        else:
            premium_dt = premium_until

        if premium_dt and premium_dt > datetime.datetime.now():
            sub_status = f"✅ Активна до {premium_dt.strftime('%d.%m.%Y %H:%M')}"
        else:
            sub_status = "❌ Не активна"
    else:
        sub_status = "❌ Не активна"

    profile_text = (
        f"👤 <b>Личный кабинет</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"📊 <b>Просмотрено видео:</b> {watched}\n"
        f"🎁 <b>Бонусных видео на балансе:</b> {bonus}\n"
        f"👑 <b>VIP-подписка:</b> {sub_status}\n"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Пополнить / Купить премиум", callback_data="premium_shop")],
            [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu")]
        ]
    )
    await callback.message.edit_text(profile_text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


# ================= PREMIUM & SHOP =================
@router.callback_query(F.data == "premium_shop")
async def premium_shop_handler(callback: CallbackQuery):
    shop_text = (
        f"⭐ <b>Магазин и Премиум-доступ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"Выберите удобный способ оплаты:\n\n"
        f"• <b>Telegram Stars (XTR)</b> — официальная валюта Telegram.\n"
        f"• <b>CryptoBot / ЮKassa</b> — оплата криптой или картами."
    )
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Оплатить через Telegram Stars", callback_data="shop_stars_menu")],
            [InlineKeyboardButton(text="💎 Оплатить криптой (CryptoBot)", callback_data="shop_crypto")],
            [InlineKeyboardButton(text="💳 Оплатить картой (ЮKassa)", callback_data="shop_fiat")],
            [InlineKeyboardButton(text="◀️ В личный кабинет", callback_data="user_profile")]
        ]
    )
    await callback.message.edit_text(shop_text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "shop_stars_menu")
async def shop_stars_menu(callback: CallbackQuery):
    text = "⭐ <b>Оплата через Telegram Stars</b>\nВыберите желаемый тариф:"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 10 звезд (10 видео)", callback_data="buy_stars_10")],
            [InlineKeyboardButton(text="🔥 100 звезд (100 видео)", callback_data="buy_stars_100")],
            [InlineKeyboardButton(text="👑 1000 звезд (Подписка на месяц)", callback_data="buy_stars_1000")],
            [InlineKeyboardButton(text="◀️ Назад в магазин", callback_data="premium_shop")]
        ]
    )
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("buy_stars_"))
async def process_buy_stars(callback: CallbackQuery):
    amount = int(callback.data.split("_")[2])
    
    if amount == 10:
        title, description, payload = "Пакет видео (10 шт.)", "Дает право просмотреть 10 видео.", "star_pack_10"
    elif amount == 100:
        title, description, payload = "Пакет видео (100 шт.)", "Дает право просмотреть 100 видео.", "star_pack_100"
    elif amount == 1000:
        title, description, payload = "VIP-подписка на 1 месяц", "Безлимитный доступ на 30 дней.", "star_sub_1000"
    else:
        await callback.answer("❌ Неизвестный тариф", show_alert=True)
        return

    prices = [LabeledPrice(label="Telegram Stars", amount=amount)]
    await callback.message.bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=title,
        description=description,
        payload=payload,
        currency="XTR",
        prices=prices,
        provider_token=""
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
    
    if "pack_10" in payload:
        cursor.execute("UPDATE users SET bonus_videos = bonus_videos + 10 WHERE user_id = ?", (user_id,))
        conn.commit()
        await message.answer("🎉 <b>Оплата прошла успешно!</b> Добавлено +10 видео.", parse_mode="HTML")
    elif "pack_100" in payload:
        cursor.execute("UPDATE users SET bonus_videos = bonus_videos + 100 WHERE user_id = ?", (user_id,))
        conn.commit()
        await message.answer("🎉 <b>Оплата прошла успешно!</b> Добавлено +100 видео.", parse_mode="HTML")
    elif "sub_1000" in payload:
        expire_date = datetime.datetime.now() + datetime.timedelta(days=30)
        cursor.execute("UPDATE users SET premium_until = ? WHERE user_id = ?", (expire_date, user_id))
        conn.commit()
        await message.answer("👑 <b>VIP-подписка активирована на 30 дней!</b>", parse_mode="HTML")


@router.callback_query(F.data == "shop_crypto")
async def shop_crypto_handler(callback: CallbackQuery):
    text = "💎 <b>Оплата через CryptoBot</b>\nИнтегрируйте API CryptoPay для генерации чеков в криптовалюте."
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="premium_shop")]])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "shop_fiat")
async def shop_fiat_handler(callback: CallbackQuery):
    text = "💳 <b>Оплата картой (ЮKassa)</b>\nУкажите `provider_token` от ЮKassa для приема платежей в рублях."
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="premium_shop")]])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


# ================= АДМИН-ПАНЕЛЬ =================
@router.callback_query(F.data == "admin_panel")
async def admin_panel_handler(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ У вас нет доступа к админ-панели.", show_alert=True)
        return

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(watched_videos) FROM users")
    total_watched = cursor.fetchone()[0] or 0

    admin_text = (
        f"🛠 <b>Админ-панель бота</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Всего пользователей:</b> {total_users}\n"
        f"📊 <b>Всего скачано видео:</b> {total_watched}\n"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Сделать рассылку", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu")]
        ]
    )
    await callback.message.edit_text(admin_text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Отказано в доступе.", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_panel")]])
    await callback.message.edit_text(
        "📢 <b>Рассылка сообщений</b>\n\nОтправьте текст, фото или видео, которое хотите разослать всем пользователям бота:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_for_broadcast)
    await callback.answer()


@router.message(AdminStates.waiting_for_broadcast)
async def admin_broadcast_process(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    await state.clear()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()

    sent_count = 0
    blocked_count = 0

    status_msg = await message.answer("⏳ Рассылка началась...")

    for (user_id,) in users:
        try:
            await message.send_copy(chat_id=user_id)
            sent_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            blocked_count += 1

    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📤 Успешно отправлено: {sent_count}\n"
        f"🚫 Заблокировали бота: {blocked_count}",
        parse_mode="HTML"
    )


# ================= YT-DLP DOWNLOADER LOGIC =================
@router.message(F.text.startswith("http"))
async def download_media_link(message: Message):
    user_id = message.from_user.id
    url = message.text.strip()
    
    cursor.execute("UPDATE users SET watched_videos = watched_videos + 1 WHERE user_id = ?", (user_id,))
    conn.commit()

    processing_msg = await message.answer("⏳ Скачиваю медиа, подождите...")

    file_id = str(uuid.uuid4())
    output_template = f"{file_id}.%(ext)s"

    ydl_opts = {
        "outtmpl": output_template,
        "format": "best[filesize<50M]/best",
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
                await processing_msg.edit_text("❌ Файл слишком большой (больше 50 МБ).")
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


# ================= GENERAL TEXT HANDLER =================
@router.message(F.text & ~F.text.startswith("http"))
async def echo_text(message: Message):
    await message.answer("💬 Отправь мне ссылку на видео (начинающуюся с http), и я скачаю её!")


# ================= MAIN FUNCTION =================
async def main():
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    
    # Подключаем роутер к диспетчеру
    dp.include_router(router)

    from aiogram.types import BotCommand
    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="premium", description="⭐ Магазин и Премиум"),
    ])

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
