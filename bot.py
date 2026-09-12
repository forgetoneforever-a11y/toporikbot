import asyncio
import logging
import os
import random
import re
import sqlite3
from contextlib import asynccontextmanager
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from fastapi import FastAPI, Request
import uvicorn

# НАСТРОЙКИ БОТА И АДМИНЫ
TOKEN = "8952197475:AAG5cY8qVLGbu-59TuHZuVWtoKg4KzCwjsQ"
ADMIN_IDS = [1320294475, 5619340928, 8870678654]

# Твой реальный юзернейм бота
BOT_USERNAME = "toporik18_bot"

WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL", "https://your-app-name.onrender.com")
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

PORT = int(os.getenv("PORT", 8000))

logging.basicConfig(level=logging.INFO)
router = Router()

# Глобальная переменная для режима технической сложности
HEAVY_WORK_MODE = False

# Инициализация базы данных SQLite с оптимизациями (WAL-режим)
conn = sqlite3.connect("bot_database.db", check_same_thread=False)
conn.execute("PRAGMA journal_mode = WAL;")
conn.execute("PRAGMA synchronous = NORMAL;")
cursor = conn.cursor()

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    repeat_mode INTEGER DEFAULT 1,
    language TEXT DEFAULT 'ru'
)
"""
)

try:
    cursor.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'ru'")
    conn.commit()
except sqlite3.OperationalError:
    pass

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT,
    caption TEXT
)
"""
)

try:
    cursor.execute("ALTER TABLE videos ADD COLUMN caption TEXT")
    conn.commit()
except sqlite3.OperationalError:
    pass

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS user_history (
    user_id INTEGER,
    video_id INTEGER,
    PRIMARY KEY (user_id, video_id)
)
"""
)

# Создаем индексы для ускорения работы базы данных
cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_lang ON users(language);")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_user ON user_history(user_id);")
conn.commit()


# Состояния для FSM
class AdminStates(StatesGroup):
    waiting_for_video = State()
    waiting_for_caption = State()


class UserStates(StatesGroup):
    waiting_for_report = State()


# Тексты и оформление для разных языков (указываем в тексте совета 25 секунд)
LANG_TEXTS = {
    "ru": {
        "welcome": (
            "✨ <b>Добро пожаловать, {name}!</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "🎬 Рады видеть вас в нашем боте.\n"
            "📌 Пожалуйста, обязательно ознакомьтесь с разделом помощи /help перед началом работы!\n"
            "━━━━━━━━━━━━━━━━━━━"
        ),
        "choose_lang": "🌍 <b>Выберите язык интерфейса</b>\nChoose your preferred language:",
        "lang_changed": "✅ Язык успешно изменен на русский!",
        "btn_random": "🎬 Смотреть случайное видео",
        "btn_help": "🆘 Помощь",
        "btn_contact": "💬 Связь с админом",
        "btn_admin": "🛠 Админ-панель",
        "help_text": (
            "📚 <b>Справочник по командам бота:</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "• /random — получить случайный видеоматериал\n"
            "• /setting — персональные настройки (вкл/выкл повтор)\n"
            "• /language — сменить язык интерфейса\n"
            "• /report — отправить сообщение администрации\n"
            "• /help — вызвать эту справку\n"
            "━━━━━━━━━━━━━━━━━━━"
        ),
        "no_videos": "📭 В базе данных пока нет ни одного видеоматериала!",
        "video_deleted_warn": "💡 <b>Совет:</b> рекомендуем пересылать понравившиеся ролики в «Избранное», так как это сообщение автоматически удалится через 25 секунд!",
    },
    "en": {
        "welcome": (
            "✨ <b>Welcome, {name}!</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "🎬 Glad to see you here.\n"
            "📌 Please read the help section via /help before getting started!\n"
            "━━━━━━━━━━━━━━━━━━━"
        ),
        "choose_lang": "🌍 <b>Please choose your language:</b>",
        "lang_changed": "✅ Language successfully changed to English!",
        "btn_random": "🎬 Watch Random Video",
        "btn_help": "🆘 Help",
        "btn_contact": "💬 Contact Admin",
        "btn_admin": "🛠 Admin Panel",
        "help_text": (
            "📚 <b>Bot Commands Guide:</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "• /random — send a random video\n"
            "• /setting — bot settings (enable/disable repeats)\n"
            "• /language — change language\n"
            "• /report — report an issue to admin\n"
            "• /help — show commands help\n"
            "━━━━━━━━━━━━━━━━━━━"
        ),
        "no_videos": "📭 There are no videos in the database yet!",
        "video_deleted_warn": "💡 <b>Tip:</b> we recommend forwarding favorite videos to Saved Messages, as this message will be deleted after 25 seconds!",
    },
    "uk": {
        "welcome": (
            "✨ <b>Вітаємо, {name}!</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "🎬 Раді бачити вас у нашому боті.\n"
            "📌 Будь ласка, прочитайте довідку за командою /help перед початком!\n"
            "━━━━━━━━━━━━━━━━━━━"
        ),
        "choose_lang": "🌍 <b>Будь ласка, виберіть мову:</b>",
        "lang_changed": "✅ Мову успішно змінено на українську!",
        "btn_random": "🎬 Випадкове відео",
        "btn_help": "🆘 Допомога",
        "btn_contact": "💬 Зв'язок з адміном",
        "btn_admin": "🛠 Адмін-панель",
        "help_text": (
            "📚 <b>Довідник по командах бота:</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "• /random — надіслати випадкове відео\n"
            "• /setting — налаштування (увімк/вимк повторення)\n"
            "• /language — змінити мову\n"
            "• /report — надіслати помилку адміністрації\n"
            "• /help — допомога та список команд\n"
            "━━━━━━━━━━━━━━━━━━━"
        ),
        "no_videos": "📭 У базі даних поки немає жодного відео!",
        "video_deleted_warn": "💡 <b>Порада:</b> рекомендуємо пересилати вподобані ролики в «Збережене», оскільки це повідомлення видалиться через 25 секунд!",
    },
    "kk": {
        "welcome": (
            "✨ <b>Қош келдіңіз, {name}!</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "🎬 Ботқа қош келдіңіз.\n"
            "📌 Бастамас бұрын /help арқылы анықтамамен танысуыңызды сұраймыз!\n"
            "━━━━━━━━━━━━━━━━━━━"
        ),
        "choose_lang": "🌍 <b>Тілді таңдаңыз / Choose language:</b>",
        "lang_changed": "✅ Тіл қазақ тіліне сәтті ауыстырылды!",
        "btn_random": "🎬 Кездейсоқ видео",
        "btn_help": "🆘 Көмек",
        "btn_contact": "💬 Әкімшімен байланыс",
        "btn_admin": "🛠 Админ-панель",
        "help_text": (
            "📚 <b>Бот командаларының анықтамасы:</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "• /random — кездейсоқ видео алу\n"
            "• /setting — баптаулар (қайталауды қосу/өшіру)\n"
            "• /language — тілді өзгерту\n"
            "• /report — әкімшілікке хабарлама жіберу\n"
            "• /help — көмек тізімі\n"
            "━━━━━━━━━━━━━━━━━━━"
        ),
        "no_videos": "📭 Дерекқорда әзірге видеолар жоқ!",
        "video_deleted_warn": "💡 <b>Кеңес:</b> ұнаған видеоларды Таңдаулыларға жіберуге кеңес береміз, себебі бұл хабарлама 25 секундтан кейін өшіріледі!",
    },
}


def get_user_lang(user_id: int) -> str:
    cursor.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row and row[0] in LANG_TEXTS:
        return row[0]
    return "ru"


def get_language_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en"),
            ],
            [
                InlineKeyboardButton(text="🇺🇦 Українська", callback_data="set_lang_uk"),
                InlineKeyboardButton(text="🇰🇿 Қазақша", callback_data="set_lang_kk"),
            ],
        ]
    )


def get_user_keyboard(is_admin: bool, lang: str = "ru"):
    t = LANG_TEXTS.get(lang, LANG_TEXTS["ru"])
    keyboard = [
        [InlineKeyboardButton(text=t["btn_random"], callback_data="random_video")],
        [
            InlineKeyboardButton(text=t["btn_help"], callback_data="help_menu"),
            InlineKeyboardButton(text=t["btn_contact"], callback_data="contact_admin"),
        ],
        [InlineKeyboardButton(text="🌍 Сменить язык / Language", callback_data="change_language")],
    ]
    if is_admin:
        keyboard.append(
            [InlineKeyboardButton(text=t["btn_admin"], callback_data="admin_panel")]
        )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Загрузить новое видео", callback_data="add_video")],
            [InlineKeyboardButton(text="🗑 Управление базой видео", callback_data="manage_videos_0")],
            [InlineKeyboardButton(text="📊 Статистика бота", callback_data="stats")],
            [InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu")],
        ]
    )


# АДМИНСКИЕ КОМАНДЫ ДЛЯ РЕЖИМА НАГРУЗКИ
@router.message(Command("work"))
async def cmd_work(message: Message):
    global HEAVY_WORK_MODE
    if message.from_user.id not in ADMIN_IDS:
        return
    HEAVY_WORK_MODE = True
    await message.answer("⚠️ Режим технической сложности **включен**. Теперь при попытке написать боту пользователи будут получать предупреждение.", parse_mode="Markdown")


@router.message(Command("rework"))
async def cmd_rework(message: Message):
    global HEAVY_WORK_MODE
    if message.from_user.id not in ADMIN_IDS:
        return
    HEAVY_WORK_MODE = False
    await message.answer("✅ Режим технической сложности **выключен**. Бот работает в штатном режиме.", parse_mode="Markdown")


# Хендлеры бота (с поддержкой глубоких ссылок в /start)
@router.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject):
    user_id = message.from_user.id
    username = message.from_user.username or "Без юзернейма"
    args = command.args

    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, repeat_mode, language) VALUES (?, ?, 1, 'ru')",
        (user_id, username),
    )
    conn.commit()

    if args and args.startswith("video_"):
        try:
            video_id = int(args.split("_")[1])
            cursor.execute("SELECT file_id, caption FROM videos WHERE id = ?", (video_id,))
            video_data = cursor.fetchone()

            if video_data:
                file_id, caption = video_data
                lang = get_user_lang(user_id)
                t = LANG_TEXTS[lang]
                is_admin = user_id in ADMIN_IDS

                chat_id = message.chat.id

                # 1. Отправляем видео (удаление через 10 секунд)
                sent_video = await message.answer_document(
                    document=file_id,
                    caption=caption,
                    parse_mode="HTML",
                    supports_streaming=True,
                    reply_markup=get_user_keyboard(is_admin, lang)
                )

                async def delete_video():
                    await asyncio.sleep(10)
                    try:
                        await message.bot.delete_message(chat_id=chat_id, message_id=sent_video.message_id)
                    except Exception:
                        pass

                asyncio.create_task(delete_video())

                # 2. Отправляем сообщение с советом (удаление через 25 секунд)
                warn_msg = await message.answer(
                    text=t["video_deleted_warn"],
                    parse_mode="HTML"
                )

                async def delete_warning():
                    await asyncio.sleep(25)
                    try:
                        await message.bot.delete_message(chat_id=chat_id, message_id=warn_msg.message_id)
                    except Exception:
                        pass

                asyncio.create_task(delete_warning())
                return
            else:
                await message.answer("❌ К сожалению, это видео было удалено или не существует.")
        except Exception:
            pass

    await message.answer(
        LANG_TEXTS["ru"]["choose_lang"],
        reply_markup=get_language_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("set_lang_"))
async def set_language_callback(callback: CallbackQuery):
    lang = callback.data.split("_")[2]
    user_id = callback.from_user.id
    name = callback.from_user.first_name

    cursor.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))
    conn.commit()

    t = LANG_TEXTS.get(lang, LANG_TEXTS["ru"])
    is_admin = user_id in ADMIN_IDS

    await callback.message.edit_text(
        t["welcome"].format(name=name),
        reply_markup=get_user_keyboard(is_admin, lang),
        parse_mode="HTML",
    )
    await callback.answer(t["lang_changed"])


@router.callback_query(F.data == "change_language")
async def change_language_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "🌍 <b>Выберите язык интерфейса</b>\nChoose your preferred language:",
        reply_markup=get_language_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(Command("language"))
async def cmd_language(message: Message):
    await message.answer(
        "🌍 <b>Выберите язык интерфейса</b>\nChoose your preferred language:",
        reply_markup=get_language_keyboard(),
        parse_mode="HTML"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    lang = get_user_lang(message.from_user.id)
    await message.answer(LANG_TEXTS[lang]["help_text"], parse_mode="HTML")


@router.callback_query(F.data == "help_menu")
async def callback_help(callback: CallbackQuery):
    lang = get_user_lang(callback.from_user.id)
    await callback.message.answer(LANG_TEXTS[lang]["help_text"], parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "contact_admin")
async def callback_contact_admin(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "💬 <b>Обратная связь</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "Опишите вашу проблему, предложение или ошибку в следующем сообщении, и администрация обязательно рассмотрит его:",
        parse_mode="HTML"
    )
    await state.set_state(UserStates.waiting_for_report)
    await callback.answer()


@router.message(Command("random"))
async def cmd_random_text(message: Message):
    fake_callback = CallbackQuery(
        id="0",
        from_user=message.from_user,
        chat_instance="0",
        message=message,
        data="random_video"
    )
    await send_random_video(fake_callback)


@router.message(Command("setting"))
async def cmd_setting(message: Message):
    user_id = message.from_user.id
    cursor.execute("SELECT repeat_mode FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    repeat_mode = row[0] if row else 1

    status_text = "Включено 🟢" if repeat_mode == 1 else "Выключено 🔴"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🔄 Повтор видео: {status_text}", callback_data="toggle_repeat"
                )
            ]
        ]
    )
    await message.answer(
        "⚙️ <b>Панель настроек</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "Здесь вы можете настроить режим повторного показа уже просмотренных видеоматериалов.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@router.callback_query(F.data == "toggle_repeat")
async def toggle_repeat_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT repeat_mode FROM users WHERE user_id = ?", (user_id,))
    current_mode = cursor.fetchone()[0]
    new_mode = 0 if current_mode == 1 else 1

    cursor.execute("UPDATE users SET repeat_mode = ? WHERE user_id = ?", (new_mode, user_id))
    conn.commit()

    if new_mode == 1:
        cursor.execute("DELETE FROM user_history WHERE user_id = ?", (user_id,))
        conn.commit()

    status_text = "Включено 🟢" if new_mode == 1 else "Выключено 🔴"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🔄 Повтор видео: {status_text}", callback_data="toggle_repeat"
                )
            ]
        ]
    )
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer("⚙️ Настройки успешно обновлены!")


@router.message(Command("report"))
async def cmd_report(message: Message, state: FSMContext):
    await message.answer(
        "💬 <b>Обратная связь</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "Опишите вашу проблему, предложение или ошибку в следующем сообщении:",
        parse_mode="HTML"
    )
    await state.set_state(UserStates.waiting_for_report)


@router.message(UserStates.waiting_for_report)
async def process_report(message: Message, state: FSMContext, bot: Bot):
    report_text = message.text
    user = message.from_user
    user_info = f"@{user.username} (ID: {user.id})" if user.username else f"ID: {user.id}"

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🚨 <b>Новое обращение от {user_info}:</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"{report_text}",
                parse_mode="HTML",
            )
        except Exception:
            pass

    await message.answer("✅ Ваше сообщение успешно передано администрации. Спасибо за обратную связь!")
    await state.clear()


# ФУНКЦИЯ ОТВЕТА АДМИНА ЧЕРЕЗ REPLY (ОТВЕТИТЬ)
@router.message(F.reply_to_message)
async def admin_reply_to_user(message: Message, bot: Bot):
    if message.from_user.id not in ADMIN_IDS:
        return

    reply_msg = message.reply_to_message
    if not reply_msg or not reply_msg.text:
        return

    match = re.search(r"ID:\s*(\d+)", reply_msg.text)
    if not match:
        return

    target_user_id = int(match.group(1))
    admin_answer = message.text

    try:
        await bot.send_message(
            chat_id=target_user_id,
            text=f"💬 <b>Ответ от администрации:</b>\n"
                 f"━━━━━━━━━━━━━━━━━━━\n"
                 f"{admin_answer}",
            parse_mode="HTML"
        )
        await message.react([{"type": "emoji", "emoji": "👍"}])
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить сообщение пользователю. Ошибка: {e}")


# ПЕРЕХВАТ ОБЫЧНЫХ СООБЩЕНИЙ (ЕСЛИ ВКЛЮЧЕН РЕЖИМ /work)
@router.message(F.text)
async def handle_any_text(message: Message):
    if HEAVY_WORK_MODE and message.from_user.id not in ADMIN_IDS:
        await message.answer("⚠️ В данный момент бот может работать технически очень тяжело. Пожалуйста, подождите.")
        return


@router.callback_query(F.data == "random_video")
async def send_random_video(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    t = LANG_TEXTS[lang]

    cursor.execute("SELECT repeat_mode FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    repeat_mode = row[0] if row else 1

    if repeat_mode == 1:
        cursor.execute("SELECT id, file_id, caption FROM videos")
    else:
        cursor.execute(
            """
            SELECT id, file_id, caption FROM videos 
            WHERE id NOT IN (SELECT video_id FROM user_history WHERE user_id = ?)
        """,
            (user_id,),
        )

    videos = cursor.fetchall()

    if not videos:
        if repeat_mode == 0:
            cursor.execute("DELETE FROM user_history WHERE user_id = ?", (user_id,))
            conn.commit()
            if isinstance(callback, CallbackQuery):
                await callback.answer(
                    "🔄 Список просмотров был автоматически сброшен.", show_alert=True
                )
            cursor.execute("SELECT id, file_id, caption FROM videos")
            videos = cursor.fetchall()

        if not videos:
            msg = t["no_videos"]
            if isinstance(callback, CallbackQuery):
                await callback.answer(msg, show_alert=True)
            else:
                await callback.message.answer(msg)
            return

    video_id, file_id, caption = random.choice(videos)

    cursor.execute(
        "INSERT OR IGNORE INTO user_history (user_id, video_id) VALUES (?, ?)",
        (user_id, video_id),
    )
    conn.commit()

    is_admin = user_id in ADMIN_IDS
    target_message = callback.message if isinstance(callback, CallbackQuery) else callback
    bot_instance = callback.bot if isinstance(callback, CallbackQuery) else target_message.bot
    chat_id = target_message.chat.id
    
    # 1. Отправляем видео (автоудаление через 10 секунд)
    sent_video = await target_message.answer_document(
        document=file_id, 
        caption=caption,
        parse_mode="HTML",
        supports_streaming=True, 
        reply_markup=get_user_keyboard(is_admin, lang)
    )
    
    if isinstance(callback, CallbackQuery):
        await callback.answer()

    async def delete_video():
        await asyncio.sleep(10)
        try:
            await bot_instance.delete_message(chat_id=chat_id, message_id=sent_video.message_id)
        except Exception:
            pass

    asyncio.create_task(delete_video())

    # 2. Отправляем предупреждение/совет (автоудаление через 25 секунд)
    warn_msg = await bot_instance.send_message(
        chat_id=chat_id,
        text=t["video_deleted_warn"],
        parse_mode="HTML"
    )

    async def delete_warning():
        await asyncio.sleep(25)
        try:
            await bot_instance.delete_message(chat_id=chat_id, message_id=warn_msg.message_id)
        except Exception:
            pass

    asyncio.create_task(delete_warning())


@router.callback_query(F.data == "admin_panel")
async def admin_panel_handler(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⛔ У вас нет доступа к этому разделу.", show_alert=True)
        return
    await callback.message.edit_text(
        "🛠 <b>Панель администратора</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "Выберите необходимое действие для управления ботом:",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: CallbackQuery):
    is_admin = callback.from_user.id in ADMIN_IDS
    lang = get_user_lang(callback.from_user.id)
    t = LANG_TEXTS[lang]
    name = callback.from_user.first_name
    await callback.message.edit_text(
        t["welcome"].format(name=name), 
        reply_markup=get_user_keyboard(is_admin, lang),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM videos")
    total_videos = cursor.fetchone()[0]

    cursor.execute("SELECT user_id, username FROM users")
    all_users = cursor.fetchall()

    users_list_str = ""
    for u_id, u_name in all_users[-10:]:
        uname_display = f"@{u_name}" if u_name != "Без юзернейма" else "Без юзернейма"
        users_list_str += f"▫️ {uname_display} (<code>{u_id}</code>)\n"

    stats_text = (
        f"📊 <b>Статистика системы:</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Всего пользователей: <b>{total_users}</b>\n"
        f"🎬 Видеоматериалов в базе: <b>{total_videos}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Последние пользователи:</b>\n"
        f"{users_list_str if users_list_str else 'Нет активности'}"
    )
    await callback.message.edit_text(
        stats_text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад в админ-панель", callback_data="admin_panel")]
            ]
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("manage_videos_"))
async def manage_videos(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return

    page = int(callback.data.split("_")[2])
    per_page = 5

    cursor.execute("SELECT id, caption FROM videos ORDER BY id DESC")
    all_videos = cursor.fetchall()
    total_videos = len(all_videos)

    if total_videos == 0:
        await callback.message.edit_text(
            "📭 <b>Управление базой видео</b>\n━━━━━━━━━━━━━━━━━━━\nВ базе данных пока нет ни одного видео.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад в админ-панель", callback_data="admin_panel")]
                ]
            ),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    start_idx = page * per_page
    end_idx = start_idx + per_page
    page_videos = all_videos[start_idx:end_idx]

    keyboard = []
    for (v_id, v_caption) in page_videos:
        if v_caption:
            clean_cap = v_caption.replace('\n', ' ')
            short_caption = f" — {clean_cap[:20]}..." if len(clean_cap) > 20 else f" — {clean_cap}"
        else:
            short_caption = " (Без подписи)"
            
        keyboard.append([InlineKeyboardButton(text=f"🎥 Видео #{v_id}{short_caption}", callback_data=f"v_info_{v_id}_{page}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"manage_videos_{page - 1}"))
    if end_idx < total_videos:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"manage_videos_{page + 1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton(text="◀️ Назад в админ-панель", callback_data="admin_panel")])

    await callback.message.edit_text(
        f"🗑 <b>Управление базой видео</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"Всего видео в базе: <b>{total_videos}</b>\n"
        f"Выберите ролик для управления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("v_info_"))
async def video_info_handler(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return

    parts = callback.data.split("_")
    video_id = int(parts[2])
    page = int(parts[3])

    cursor.execute("SELECT caption FROM videos WHERE id = ?", (video_id,))
    row = cursor.fetchone()
    if not row:
        await callback.answer("❌ Видео не найдено!", show_alert=True)
        return

    caption = row[0] or "Без подписи"
    deep_link = f"https://t.me/{BOT_USERNAME}?start=video_{video_id}"

    text = (
        f"🎬 <b>Видео #{video_id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📝 <b>Подпись:</b> {caption}\n\n"
        f"🔗 <b>Прямая ссылка на видео:</b>\n"
        f"<code>{deep_link}</code>"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить это видео", callback_data=f"del_video_{video_id}_{page}")],
            [InlineKeyboardButton(text="◀️ Назад к списку", callback_data=f"manage_videos_{page}")]
        ]
    )

    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("del_video_"))
async def delete_video_handler(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return

    parts = callback.data.split("_")
    video_id = int(parts[2])
    page = int(parts[3])

    cursor.execute("DELETE FROM videos WHERE id = ?", (video_id,))
    cursor.execute("DELETE FROM user_history WHERE video_id = ?", (video_id,))
    conn.commit()

    await callback.answer(f"✅ Видео #{video_id} успешно удалено из базы!", show_alert=True)
    
    callback.data = f"manage_videos_{page}"
    await manage_videos(callback)


@router.callback_query(F.data == "add_video")
async def admin_add_video_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.message.edit_text(
        "📤 <b>Добавление видео (Шаг 1/2)</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "Отправьте видеофайл, который хотите добавить в базу данных:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_panel")]
            ]
        ),
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_for_video)
    await callback.answer()


@router.message(AdminStates.waiting_for_video, F.video | F.document)
async def admin_get_video_file(message: Message, state: FSMContext):
    file_id = None
    if message.video:
        file_id = message.video.file_id
    elif message.document:
        if message.document.mime_type and "video" in message.document.mime_type:
            file_id = message.document.file_id
        elif message.document.file_name and message.document.file_name.lower().endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm')):
            file_id = message.document.file_id

    if file_id:
        await state.update_data(file_id=file_id)
        
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⏭ Пропустить (без подписи)", callback_data="skip_caption")],
                [InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_panel")]
            ]
        )
        await message.answer(
            "📝 <b>Добавление видео (Шаг 2/2)</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "Теперь отправьте **текст подписи** к этому видео (можно использовать HTML-теги) или нажмите кнопку ниже:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await state.set_state(AdminStates.waiting_for_caption)
    else:
        await message.answer("❌ Этот файл не похож на видео. Пожалуйста, отправьте видеофайл в формате MP4 или документом.")


@router.message(AdminStates.waiting_for_video)
async def admin_wrong_video_type(message: Message):
    await message.answer("❌ Пожалуйста, отправьте видео или видеофайл.")


@router.message(AdminStates.waiting_for_caption, F.text)
async def admin_save_video_with_caption(message: Message, state: FSMContext):
    data = await state.get_data()
    file_id = data.get("file_id")
    caption = message.text

    cursor.execute("INSERT INTO videos (file_id, caption) VALUES (?, ?)", (file_id, caption))
    conn.commit()

    is_admin = message.from_user.id in ADMIN_IDS
    lang = get_user_lang(message.from_user.id)
    await message.answer(
        "✅ <b>Успешно!</b> Видео с подписью добавлено в базу данных.",
        reply_markup=get_user_keyboard(is_admin, lang),
        parse_mode="HTML"
    )
    await state.clear()


@router.callback_query(AdminStates.waiting_for_caption, F.data == "skip_caption")
async def admin_save_video_no_caption(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    file_id = data.get("file_id")

    cursor.execute("INSERT INTO videos (file_id, caption) VALUES (?, NULL)", (file_id,))
    conn.commit()

    is_admin = callback.from_user.id in ADMIN_IDS
    lang = get_user_lang(callback.from_user.id)
    
    await callback.message.edit_text("✅ Видео успешно добавлено в базу данных (без подписи)!")
    await callback.message.answer(
        "Главное меню:",
        reply_markup=get_user_keyboard(is_admin, lang),
    )
    await state.clear()
    await callback.answer()


# Инициализация бота и FastAPI с современным lifespan-менеджером
bot = Bot(token=TOKEN)
dp = Dispatcher()
dp.include_router(router)

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
        logging.info(f"✅ Вебхук успешно установлен на: {WEBHOOK_URL}")
    except Exception as e:
        logging.error(f"❌ Ошибка при установке вебхука: {e}")
    
    yield
    
    try:
        await bot.session.close()
        logging.info("🛑 Сессия бота закрыта.")
    except Exception as e:
        logging.error(f"❌ Ошибка при закрытии сессии: {e}")

app = FastAPI(lifespan=lifespan)


@app.post(WEBHOOK_PATH)
async def bot_webhook(request: Request):
    from aiogram.types import Update
    try:
        update_data = await request.json()
        update = Update.model_validate(update_data, context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception as e:
        logging.error(f"❌ Ошибка обработки апдейта от Telegram: {e}")
    return {"status": "ok"}


@app.get("/")
@app.head("/")
async def index():
    return {"status": "Bot is alive!"}


if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=PORT)
