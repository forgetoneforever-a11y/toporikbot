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
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    FSInputFile,
)
from fastapi import FastAPI, Request
import uvicorn
import yt_dlp

# НАСТРОЙКИ БОТА И АДМИНЫ
TOKEN = "8952197475:AAG5cY8qVLGbu-59TuHZuVWtoKg4KzCwjsQ"
ADMIN_IDS = [1320294475, 5619340928, 8870678654]
BOT_USERNAME = "toporik18_bot"

WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL", "https://your-app-name.onrender.com")
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
PORT = int(os.getenv("PORT", 8000))

logging.basicConfig(level=logging.INFO)
router = Router()
HEAVY_WORK_MODE = False

# Инициализация базы данных SQLite
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

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT,
    caption TEXT,
    category TEXT DEFAULT 'kids'
)
"""
)

for col_def in [
    ("language", "TEXT DEFAULT 'ru'"),
    ("caption", "TEXT"),
    ("category", "TEXT DEFAULT 'kids'"),
]:
    try:
        cursor.execute(f"ALTER TABLE users ADD COLUMN {col_def[0]} {col_def[1]}")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute(f"ALTER TABLE videos ADD COLUMN {col_def[0]} {col_def[1]}")
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
cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_lang ON users(language);")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_user ON user_history(user_id);")
conn.commit()


# Состояния FSM для админки и репортов
class AdminStates(StatesGroup):
    waiting_for_category = State()
    waiting_for_video = State()
    waiting_for_caption = State()


class UserStates(StatesGroup):
    waiting_for_report = State()


# Тексты интерфейса
LANG_TEXTS = {
    "ru": {
        "welcome": (
            "✨ <b>Главное меню бота</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "🎬 Выберите категорию или просто отправьте ссылку на видео/музыку (YouTube, TikTok и др.), чтобы скачать её.\n"
            "📌 Используйте /help для справки."
        ),
        "choose_lang": "🌍 <b>Выберите язык интерфейса</b>\nChoose your preferred language:",
        "lang_changed": "✅ Язык успешно изменен на русский!",
        "btn_random": "🎬 Случайное видео",
        "btn_kids": "🧸 Категория: Kids",
        "btn_porno": "🔥 Категория: Porno",
        "btn_help": "🆘 Помощь",
        "btn_contact": "💬 Связь с админом",
        "btn_admin": "🛠 Админ-панель",
        "help_text": (
            "📚 <b>Справочник по командам бота:</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "• 🔗 <i>Просто отправьте ссылку</i> (YouTube, TikTok и др.) — бот скачает медиафайл\n"
            "• /random — получить случайный видеоматериал\n"
            "• /setting — персональные настройки (повтор видео)\n"
            "• /language — сменить язык интерфейса\n"
            "• /report — отправить сообщение администрации\n"
            "━━━━━━━━━━━━━━━━━━━"
        ),
        "no_videos": "📭 В выбранной категории пока нет ни одного видеоматериала!",
        "video_deleted_warn": "💡 <b>Совет:</b> рекомендуем пересылать понравившиеся ролики в «Избранное», так как это сообщение автоматически удалится через 25 секунд!",
    }
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
        [
            InlineKeyboardButton(text=t["btn_kids"], callback_data="watch_kids"),
            InlineKeyboardButton(text=t["btn_porno"], callback_data="watch_porno"),
        ],
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


# ==========================================
# ФУНКЦИЯ: СКАЧИВАНИЕ ВИДЕО/МУЗЫКИ ПО ССЫЛКЕ (yt-dlp)
# ==========================================
@router.message(F.text.regexp(r"https?://[^\s]+"))
async def download_media_link(message: Message):
    url = message.text.strip()
    
    if len(url.split()) > 1 or url.startswith("/"):
        return

    processing_msg = await message.answer("⏳ <b>Скачиваю медиа по ссылке...</b> Пожалуйста, подождите.", parse_mode="HTML")
    
    output_template = f"downloads/media_{message.from_user.id}_%(id)s.%(ext)s"
    os.makedirs("downloads", exist_ok=True)

    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': output_template,
        'max_filesize': 50 * 1024 * 1024,  # Ограничение 50 МБ для Telegram
        'noplaylist': True,
    }

    downloaded_file = None
    try:
        def run_dl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info)

        downloaded_file = await asyncio.to_thread(run_dl)

        if downloaded_file and os.path.exists(downloaded_file):
            file_size = os.path.getsize(downloaded_file)
            if file_size > 50 * 1024 * 1024:
                await message.bot.edit_message_text(
                    "❌ Файл слишком большой (превышает лимит Telegram в 50 МБ).",
                    chat_id=message.chat.id,
                    message_id=processing_msg.message_id
                )
                return

            input_file = FSInputFile(downloaded_file)
            
            if downloaded_file.endswith(('.mp3', '.m4a', '.wav', '.opus', '.flac')):
                await message.answer_audio(audio=input_file, caption="🎵 Скачанная музыка через бота")
            else:
                await message.answer_video(video=input_file, caption="📥 Скачанный файл через бота", supports_streaming=True)
            
            await message.bot.delete_message(chat_id=message.chat.id, message_id=processing_msg.message_id)
        else:
            raise Exception("Файл не был найден после скачивания.")

    except Exception as e:
        logging.error(f"Ошибка yt-dlp: {e}")
        try:
            await message.bot.edit_message_text(
                "❌ <b>Не удалось скачать медиа по ссылке.</b>\nВозможные причины: видео защищено, удалено или файл весит больше 50 МБ.",
                chat_id=message.chat.id,
                message_id=processing_msg.message_id,
                parse_mode="HTML"
            )
        except Exception:
            pass
    finally:
        if downloaded_file and os.path.exists(downloaded_file):
            try:
                os.remove(downloaded_file)
            except Exception:
                pass


# /start КОМАНДА
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

    lang = get_user_lang(user_id)
    t = LANG_TEXTS.get(lang, LANG_TEXTS["ru"])
    is_admin = user_id in ADMIN_IDS

    if args and args.startswith("video_"):
        try:
            video_id = int(args.split("_")[1])
            cursor.execute("SELECT file_id, caption, category FROM videos WHERE id = ?", (video_id,))
            video_data = cursor.fetchone()

            if video_data:
                file_id, caption, category = video_data
                chat_id = message.chat.id

                sent_video = await message.answer_document(
                    document=file_id,
                    caption=caption,
                    parse_mode="HTML",
                    supports_streaming=True,
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🎬 Еще видео", callback_data=f"next_v_{category}")],
                            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu_fixed")]
                        ]
                    )
                )

                async def delete_video():
                    await asyncio.sleep(10)
                    try:
                        await message.bot.delete_message(chat_id=chat_id, message_id=sent_video.message_id)
                    except Exception:
                        pass
                asyncio.create_task(delete_video())

                warn_msg = await message.answer(text=t["video_deleted_warn"], parse_mode="HTML")

                async def delete_warning():
                    await asyncio.sleep(25)
                    try:
                        await message.bot.delete_message(chat_id=chat_id, message_id=warn_msg.message_id)
                    except Exception:
                        pass
                asyncio.create_task(delete_warning())
                return
        except Exception:
            pass

    await message.answer(
        t["welcome"],
        reply_markup=get_user_keyboard(is_admin, lang),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "main_menu_fixed")
async def main_menu_fixed(callback: CallbackQuery):
    is_admin = callback.from_user.id in ADMIN_IDS
    lang = get_user_lang(callback.from_user.id)
    t = LANG_TEXTS[lang]
    await callback.message.answer(
        t["welcome"],
        reply_markup=get_user_keyboard(is_admin, lang),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: CallbackQuery):
    is_admin = callback.from_user.id in ADMIN_IDS
    lang = get_user_lang(callback.from_user.id)
    t = LANG_TEXTS[lang]
    await callback.message.edit_text(
        t["welcome"],
        reply_markup=get_user_keyboard(is_admin, lang),
        parse_mode="HTML"
    )


# ЛОГИКА ОТПРАВКИ ВИДЕО ПО КАТЕГОРИЯМ И РАНДОМУ
@router.callback_query(F.data.in_({"watch_kids", "watch_porno", "random_video"}) | F.data.startswith("next_v_"))
async def send_video_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    t = LANG_TEXTS[lang]

    category = None
    if callback.data == "watch_kids":
        category = "kids"
    elif callback.data == "watch_porno":
        category = "porno"
    elif callback.data.startswith("next_v_"):
        category = callback.data.split("_")[2]

    cursor.execute("SELECT repeat_mode FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    repeat_mode = row[0] if row else 1

    if category:
        if repeat_mode == 1:
            cursor.execute("SELECT id, file_id, caption, category FROM videos WHERE category = ?", (category,))
        else:
            cursor.execute(
                """
                SELECT id, file_id, caption, category FROM videos 
                WHERE category = ? AND id NOT IN (SELECT video_id FROM user_history WHERE user_id = ?)
            """,
                (category, user_id),
            )
    else:
        if repeat_mode == 1:
            cursor.execute("SELECT id, file_id, caption, category FROM videos")
        else:
            cursor.execute(
                """
                SELECT id, file_id, caption, category FROM videos 
                WHERE id NOT IN (SELECT video_id FROM user_history WHERE user_id = ?)
            """,
                (user_id,),
            )

    videos = cursor.fetchall()

    if not videos and repeat_mode == 0:
        cursor.execute("DELETE FROM user_history WHERE user_id = ?", (user_id,))
        conn.commit()
        if category:
            cursor.execute("SELECT id, file_id, caption, category FROM videos WHERE category = ?", (category,))
        else:
            cursor.execute("SELECT id, file_id, caption, category FROM videos")
        videos = cursor.fetchall()

    if not videos:
        await callback.answer(t["no_videos"], show_alert=True)
        return

    video_id, file_id, caption, v_category = random.choice(videos)

    cursor.execute(
        "INSERT OR IGNORE INTO user_history (user_id, video_id) VALUES (?, ?)",
        (user_id, video_id),
    )
    conn.commit()

    chat_id = callback.message.chat.id

    sent_video = await callback.message.answer_document(
        document=file_id,
        caption=caption,
        parse_mode="HTML",
        supports_streaming=True,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎬 Еще видео", callback_data=f"next_v_{v_category}")],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu_fixed")]
            ]
        )
    )
    await callback.answer()

    async def delete_video():
        await asyncio.sleep(10)
        try:
            await callback.bot.delete_message(chat_id=chat_id, message_id=sent_video.message_id)
        except Exception:
            pass
    asyncio.create_task(delete_video())

    warn_msg = await callback.message.answer(text=t["video_deleted_warn"], parse_mode="HTML")

    async def delete_warning():
        await asyncio.sleep(25)
        try:
            await callback.bot.delete_message(chat_id=chat_id, message_id=warn_msg.message_id)
        except Exception:
            pass
    asyncio.create_task(delete_warning())


# ЯЗЫКОВЫЕ И ВСПОМОГАТЕЛЬНЫЕ КОМАНДЫ
@router.callback_query(F.data.startswith("set_lang_"))
async def set_language_callback(callback: CallbackQuery):
    lang = callback.data.split("_")[2]
    user_id = callback.from_user.id

    cursor.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))
    conn.commit()

    t = LANG_TEXTS.get(lang, LANG_TEXTS["ru"])
    is_admin = user_id in ADMIN_IDS

    await callback.message.edit_text(
        t["welcome"],
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
        "Опишите вашу проблему или предложение в следующем сообщении:",
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
    await send_video_handler(fake_callback)


@router.message(Command("setting"))
async def cmd_setting(message: Message):
    user_id = message.from_user.id
    cursor.execute("SELECT repeat_mode FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    repeat_mode = row[0] if row else 1
    status_text = "Включено 🟢" if repeat_mode == 1 else "Выключено 🔴"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🔄 Повтор видео: {status_text}", callback_data="toggle_repeat")]
        ]
    )
    await message.answer("⚙️ <b>Панель настроек</b>", reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "toggle_repeat")
async def toggle_repeat_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT repeat_mode FROM users WHERE user_id = ?", (user_id,))
    current_mode = cursor.fetchone()[0]
    new_mode = 0 if current_mode == 1 else 1

    cursor.execute("UPDATE users SET repeat_mode = ? WHERE user_id = ?", (new_mode, user_id))
    conn.commit()

    status_text = "Включено 🟢" if new_mode == 1 else "Выключено 🔴"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🔄 Повтор видео: {status_text}", callback_data="toggle_repeat")]
        ]
    )
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer("⚙️ Настройки обновлены!")


@router.message(Command("report"))
async def cmd_report(message: Message, state: FSMContext):
    await message.answer("💬 Опишите проблему в следующем сообщении:", parse_mode="HTML")
    await state.set_state(UserStates.waiting_for_report)


@router.message(UserStates.waiting_for_report)
async def process_report(message: Message, state: FSMContext, bot: Bot):
    report_text = message.text
    user = message.from_user
    user_info = f"@{user.username} (ID: {user.id})" if user.username else f"ID: {user.id}"

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, f"🚨 <b>Обращение от {user_info}:</b>\n{report_text}", parse_mode="HTML")
        except Exception:
            pass
    await message.answer("✅ Ваше сообщение отправлено администрации!")
    await state.clear()


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
    try:
        await bot.send_message(target_user_id, f"💬 <b>Ответ администрации:</b>\n{message.text}", parse_mode="HTML")
        await message.react([{"type": "emoji", "emoji": "👍"}])
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки: {e}")


# АДМИН-ПАНЕЛЬ
@router.callback_query(F.data == "admin_panel")
async def admin_panel_handler(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.message.edit_text("🛠 <b>Панель администратора</b>", reply_markup=get_admin_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM videos")
    total_videos = cursor.fetchone()[0]
    await callback.message.edit_text(
        f"📊 <b>Статистика:</b>\n👥 Пользователей: {total_users}\n🎬 Видео в базе: {total_videos}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]]),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "add_video")
async def admin_add_video_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🧸 Kids", callback_data="category_kids"),
                InlineKeyboardButton(text="🔥 Porno", callback_data="category_porno"),
            ],
            [InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_panel")]
        ]
    )
    await callback.message.edit_text("📤 <b>Выберите категорию для загрузки видео:</b>", reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(AdminStates.waiting_for_category)
    await callback.answer()


@router.callback_query(AdminStates.waiting_for_category, F.data.startswith("category_"))
async def admin_get_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split("_")[1]
    await state.update_data(category=category)
    await callback.message.edit_text(
        f"📤 <b>Загрузка в категорию: {category.upper()} (Шаг 1/2)</b>\nОтправьте видеофайл:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_panel")]]),
        parse_mode="HTML"
    )
    await state.set_state(AdminStates.waiting_for_video)
    await callback.answer()


@router.message(AdminStates.waiting_for_video, F.video | F.document)
async def admin_get_video_file(message: Message, state: FSMContext):
    file_id = message.video.file_id if message.video else message.document.file_id
    if file_id:
        await state.update_data(file_id=file_id)
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⏭ Пропустить подпись", callback_data="skip_caption")],
                [InlineKeyboardButton(text="◀️ Отмена", callback_data="admin_panel")]
            ]
        )
        await message.answer("📝 <b>Шаг 2/2:</b> Отправьте текст подписи к этому видео:", reply_markup=keyboard, parse_mode="HTML")
        await state.set_state(AdminStates.waiting_for_caption)
    else:
        await message.answer("❌ Ошибка: отправьте видеофайл.")


@router.message(AdminStates.waiting_for_caption, F.text)
async def admin_save_video_with_caption(message: Message, state: FSMContext):
    data = await state.get_data()
    file_id = data.get("file_id")
    category = data.get("category", "kids")
    caption = message.text

    cursor.execute("INSERT INTO videos (file_id, caption, category) VALUES (?, ?, ?)", (file_id, caption, category))
    conn.commit()

    is_admin = message.from_user.id in ADMIN_IDS
    lang = get_user_lang(message.from_user.id)
    await message.answer("✅ Видео с подписью успешно добавлено в базу!", reply_markup=get_user_keyboard(is_admin, lang), parse_mode="HTML")
    await state.clear()


@router.callback_query(AdminStates.waiting_for_caption, F.data == "skip_caption")
async def admin_save_video_no_caption(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    file_id = data.get("file_id")
    category = data.get("category", "kids")

    cursor.execute("INSERT INTO videos (file_id, caption, category) VALUES (?, NULL, ?)", (file_id, category))
    conn.commit()

    is_admin = callback.from_user.id in ADMIN_IDS
    lang = get_user_lang(callback.from_user.id)
    await callback.message.edit_text("✅ Видео успешно добавлено (без подписи)!")
    await callback.message.answer("Главное меню:", reply_markup=get_user_keyboard(is_admin, lang))
    await state.clear()
    await callback.answer()


@router.callback_query(F.data.startswith("manage_videos_"))
async def manage_videos(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    page = int(callback.data.split("_")[2])
    per_page = 5
    cursor.execute("SELECT id, caption, category FROM videos ORDER BY id DESC")
    all_videos = cursor.fetchall()
    total = len(all_videos)

    if total == 0:
        await callback.message.edit_text("📭 В базе нет видео.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]]))
        return

    start, end = page * per_page, (page + 1) * per_page
    keyboard = []
    for v_id, v_cap, v_cat in all_videos[start:end]:
        cap_text = f" — {v_cap[:15]}..." if v_cap else ""
        keyboard.append([InlineKeyboardButton(text=f"[{v_cat}] #{v_id}{cap_text}", callback_data=f"v_info_{v_id}_{page}")])
    
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"manage_videos_{page - 1}"))
    if end < total: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"manage_videos_{page + 1}"))
    if nav: keyboard.append(nav)
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")])

    await callback.message.edit_text(f"🗑 <b>Управление видео (Всего: {total})</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("v_info_"))
async def video_info_handler(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    _, _, v_id, page = callback.data.split("_")
    v_id = int(v_id)
    cursor.execute("SELECT caption, category FROM videos WHERE id = ?", (v_id,))
    row = cursor.fetchone()
    if not row:
        await callback.answer("❌ Не найдено", show_alert=True)
        return
    cap, cat = row
    link = f"https://t.me/{BOT_USERNAME}?start=video_{v_id}"
    await callback.message.edit_text(
        f"🎬 <b>Видео #{v_id}</b>\n📂 Категория: <b>{cat}</b>\n📝 Подпись: {cap or 'Нет'}\n\n🔗 <code>{link}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del_video_{v_id}_{page}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"manage_videos_{page}")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("del_video_"))
async def delete_video_handler(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    _, _, v_id, page = callback.data.split("_")
    v_id = int(v_id)
    cursor.execute("DELETE FROM videos WHERE id = ?", (v_id,))
    cursor.execute("DELETE FROM user_history WHERE video_id = ?", (v_id,))
    conn.commit()
    await callback.answer(f"✅ Видео #{v_id} удалено!", show_alert=True)
    callback.data = f"manage_videos_{page}"
    await manage_videos(callback)


# ИНИЦИАЛИЗАЦИЯ И ЗАПУСК ЧЕРЕЗ FASTAPI (WEBHOOK)
bot = Bot(token=TOKEN)
dp = Dispatcher()
dp.include_router(router)

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
        logging.info("✅ Вебхук установлен")
        
        await bot.set_my_commands([
            BotCommand(command="random", description="🎬 Случайное видео"),
            BotCommand(command="setting", description="⚙️ Настройки повтора"),
            BotCommand(command="language", description="🌍 Сменить язык"),
            BotCommand(command="report", description="💬 Связь с админом"),
            BotCommand(command="help", description="🆘 Справка"),
        ])
    except Exception as e:
        logging.error(f"❌ Ошибка запуска: {e}")
    yield
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.post(WEBHOOK_PATH)
async def bot_webhook(request: Request):
    from aiogram.types import Update
    try:
        update = Update.model_validate(await request.json(), context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception as e:
        logging.error(f"❌ Ошибка апдейта: {e}")
    return {"status": "ok"}

@app.get("/")
@app.head("/")
async def index():
    return {"status": "Bot is alive!"}

if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=PORT)
