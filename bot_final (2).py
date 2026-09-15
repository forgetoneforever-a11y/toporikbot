import asyncio
import html
import logging
import os
import random
import sqlite3
import time
from contextlib import asynccontextmanager
from collections import defaultdict
import threading
from typing import Optional

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
    Update,
)
from fastapi import FastAPI, Request
import uvicorn


# ============================================================
# НАСТРОЙКИ
# ============================================================

# Токен можно оставить здесь или задать через BOT_TOKEN в Render.
TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [1320294475, 5619340928, 8870678654]
BOT_USERNAME = "toporik18_bot"

WEBHOOK_HOST = os.getenv(
    "RENDER_EXTERNAL_URL",
    "https://your-app-name.onrender.com",
).rstrip("/")

# Отдельный секрет для webhook. Если не задан, используется случайный
# путь с токеном, как и раньше.
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
PORT = int(os.getenv("PORT", 8000))

DB_PATH = os.getenv("DB_PATH", "bot_database.db")

# Небольшой cooldown защищает от спама по кнопке "Еще видео".
VIDEO_COOLDOWN = 0.35

# Максимальная длина подписи, которую сохраняем/показываем как caption.
MAX_CAPTION_LENGTH = 1024
SUBSCRIBER_VIDEO_COOLDOWN = 2 * 60 * 60


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("telegram_bot")

router = Router()
HEAVY_WORK_MODE = False

# FSM-состояния объявляем ДО регистрации handlers.
# Иначе Python падает при импорте файла с NameError.
class AdminStates(StatesGroup):
    waiting_for_category = State()
    waiting_for_video = State()
    waiting_for_caption = State()


class UserStates(StatesGroup):
    waiting_for_report = State()
    waiting_for_subscriber_video = State()


# Блокировки по пользователю: не дадим двум быстрым кликам одновременно
# выбрать один и тот же ролик при выключенном повторе.
_user_locks = defaultdict(asyncio.Lock)
_last_video_request = {}


# ============================================================
# ТЕКСТЫ
# ============================================================

LANG_TEXTS = {
    "ru": {
        "welcome": (
            "✨ <b>Главное меню бота</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "🎬 Выберите категорию или нажмите кнопку ниже для получения контента.\n"
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
            "• /random — получить случайное видеоматериал\n"
            "• /setting — персональные настройки (вкл/выкл повтор)\n"
            "• /language — сменить язык интерфейса\n"
            "• /report — отправить сообщение администрации\n"
            "• /help — вызвать эту справку\n"
            "━━━━━━━━━━━━━━━━━━━"
        ),
        "no_videos": "📭 В выбранной категории пока нет ни одного видеоматериала!",
        "video_deleted_warn": (
            "💡 <b>Совет:</b> рекомендуем пересылать понравившиеся ролики "
            "в «Избранное», так как это сообщение автоматически удалится через 25 секунд!"
        ),
        "contact_text": (
            "💬 <b>Обратная связь</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "Опишите вашу проблему или предложение в следующем сообщении:"
        ),
        "report_sent": "✅ Ваше сообщение отправлено администрации!",
        "report_prompt": "💬 Опишите проблему в следующем сообщении:",
        "settings_title": "⚙️ <b>Панель настроек</b>",
        "repeat_on": "Включено 🟢",
        "repeat_off": "Выключено 🔴",
        "settings_updated": "⚙️ Настройки обновлены!",
    },
    "en": {
        "welcome": (
            "✨ <b>Main menu</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "🎬 Choose a category or press the button below to get content.\n"
            "📌 Use /help for help."
        ),
        "choose_lang": "🌍 <b>Choose interface language</b>\nВыберите язык интерфейса:",
        "lang_changed": "✅ Language changed to English!",
        "btn_random": "🎬 Random video",
        "btn_kids": "🧸 Category: Kids",
        "btn_porno": "🔥 Category: Porno",
        "btn_help": "🆘 Help",
        "btn_contact": "💬 Contact admin",
        "btn_admin": "🛠 Admin panel",
        "help_text": (
            "📚 <b>Bot commands:</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "• /random — get a random video\n"
            "• /setting — repeat settings\n"
            "• /language — change interface language\n"
            "• /report — contact administration\n"
            "• /help — show this help\n"
            "━━━━━━━━━━━━━━━━━━━"
        ),
        "no_videos": "📭 There are no videos in the selected category yet!",
        "video_deleted_warn": (
            "💡 <b>Tip:</b> save videos you like to Saved Messages because "
            "this message will be automatically deleted in 25 seconds!"
        ),
        "contact_text": (
            "💬 <b>Feedback</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "Describe your problem or suggestion in the next message:"
        ),
        "report_sent": "✅ Your message has been sent to the administration!",
        "report_prompt": "💬 Describe the problem in your next message:",
        "settings_title": "⚙️ <b>Settings</b>",
        "repeat_on": "Enabled 🟢",
        "repeat_off": "Disabled 🔴",
        "settings_updated": "⚙️ Settings updated!",
    },
    "uk": {
        "welcome": (
            "✨ <b>Головне меню бота</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "🎬 Оберіть категорію або натисніть кнопку нижче для отримання контенту.\n"
            "📌 Використовуйте /help для довідки."
        ),
        "choose_lang": "🌍 <b>Оберіть мову інтерфейсу</b>\nChoose your preferred language:",
        "lang_changed": "✅ Мову успішно змінено на українську!",
        "btn_random": "🎬 Випадкове відео",
        "btn_kids": "🧸 Категорія: Kids",
        "btn_porno": "🔥 Категорія: Porno",
        "btn_help": "🆘 Допомога",
        "btn_contact": "💬 Зв'язок з адміном",
        "btn_admin": "🛠 Панель адміністратора",
        "help_text": (
            "📚 <b>Команди бота:</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "• /random — отримати випадкове відео\n"
            "• /setting — налаштування повтору\n"
            "• /language — змінити мову\n"
            "• /report — звернутися до адміністрації\n"
            "• /help — ця довідка\n"
            "━━━━━━━━━━━━━━━━━━━"
        ),
        "no_videos": "📭 У вибраній категорії поки немає відео!",
        "video_deleted_warn": (
            "💡 <b>Порада:</b> зберігайте вподобані ролики в «Збережені повідомлення», "
            "оскільки це повідомлення автоматично видалиться через 25 секунд!"
        ),
        "contact_text": (
            "💬 <b>Зворотний зв'язок</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "Опишіть проблему або пропозицію в наступному повідомленні:"
        ),
        "report_sent": "✅ Ваше повідомлення надіслано адміністрації!",
        "report_prompt": "💬 Опишіть проблему в наступному повідомленні:",
        "settings_title": "⚙️ <b>Налаштування</b>",
        "repeat_on": "Увімкнено 🟢",
        "repeat_off": "Вимкнено 🔴",
        "settings_updated": "⚙️ Налаштування оновлено!",
    },
    "kk": {
        "welcome": (
            "✨ <b>Басты мәзір</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "🎬 Санатты таңдаңыз немесе төмендегі батырманы басыңыз.\n"
            "📌 Көмек үшін /help пайдаланыңыз."
        ),
        "choose_lang": "🌍 <b>Интерфейс тілін таңдаңыз</b>\nChoose your preferred language:",
        "lang_changed": "✅ Тіл қазақшаға өзгертілді!",
        "btn_random": "🎬 Кездейсоқ видео",
        "btn_kids": "🧸 Санат: Kids",
        "btn_porno": "🔥 Санат: Porno",
        "btn_help": "🆘 Көмек",
        "btn_contact": "💬 Әкімшімен байланыс",
        "btn_admin": "🛠 Әкімші панелі",
        "help_text": (
            "📚 <b>Бот командалары:</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "• /random — кездейсоқ видео алу\n"
            "• /setting — қайталау баптаулары\n"
            "• /language — интерфейс тілін өзгерту\n"
            "• /report — әкімшілікке хабарласу\n"
            "• /help — осы анықтама\n"
            "━━━━━━━━━━━━━━━━━━━"
        ),
        "no_videos": "📭 Таңдалған санатта әзірге видео жоқ!",
        "video_deleted_warn": (
            "💡 <b>Кеңес:</b> ұнаған роликтерді «Сақталған хабарламаларға» жіберіңіз, "
            "өйткені бұл хабарлама 25 секундтан кейін автоматты түрде өшеді!"
        ),
        "contact_text": (
            "💬 <b>Кері байланыс</b>\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "Мәселе немесе ұсынысыңызды келесі хабарламада жазыңыз:"
        ),
        "report_sent": "✅ Хабарыңыз әкімшілікке жіберілді!",
        "report_prompt": "💬 Мәселені келесі хабарламада жазыңыз:",
        "settings_title": "⚙️ <b>Баптаулар</b>",
        "repeat_on": "Қосулы 🟢",
        "repeat_off": "Өшірулі 🔴",
        "settings_updated": "⚙️ Баптаулар жаңартылды!",
    },
}


SUPPORTED_LANGS = set(LANG_TEXTS)


def get_texts(lang: str):
    return LANG_TEXTS.get(lang, LANG_TEXTS["ru"])


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
    t = get_texts(lang)
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
        [
            InlineKeyboardButton(
                text="📹 Видео от подписчиков",
                callback_data="subscriber_videos",
            )
        ],
        [
            InlineKeyboardButton(
                text="🌍 Сменить язык / Language",
                callback_data="change_language",
            )
        ],
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


def get_subscriber_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👀 Смотреть видео от подписчиков", callback_data="watch_subscriber")],
            [InlineKeyboardButton(text="➕ Добавить своё видео", callback_data="add_subscriber_video")],
            [InlineKeyboardButton(text="◀️ В главное меню", callback_data="main_menu")],
        ]
    )


def get_subscriber_moderation_keyboard(submission_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Принять — Kids", callback_data=f"sub_accept_{submission_id}_kids"),
                InlineKeyboardButton(text="✅ Принять — Porno", callback_data=f"sub_accept_{submission_id}_porno"),
            ],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"sub_reject_{submission_id}")],
        ]
    )


def get_repeat_keyboard(repeat_mode: int, lang: str):
    t = get_texts(lang)
    status = t["repeat_on"] if repeat_mode == 1 else t["repeat_off"]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🔄 Повтор видео: {status}",
                    callback_data="toggle_repeat",
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ В главное меню",
                    callback_data="main_menu",
                )
            ],
        ]
    )


# ============================================================
# БАЗА ДАННЫХ
# ============================================================

class Database:
    """
    SQLite остается простым и совместимым с текущей базой, но:
    - запросы выполняются вне event loop через asyncio.to_thread;
    - каждая операция получает короткоживущую connection;
    - WAL + busy_timeout уменьшают блокировки;
    - тяжелая выдача видео использует кэш, а не SELECT всей таблицы
      на каждый клик.
    """

    def __init__(self, path: str):
        self.path = path
        self.write_lock = asyncio.Lock()
        self._thread_local = threading.local()
        self._init_sync()

    def _connect(self):
        # Один постоянный connection на рабочий thread. Это заметно дешевле,
        # чем открывать/закрывать SQLite на каждом запросе при высокой нагрузке.
        db = getattr(self._thread_local, "connection", None)
        if db is None:
            db = sqlite3.connect(
                self.path,
                timeout=15,
                check_same_thread=True,
            )
            db.execute("PRAGMA synchronous=NORMAL")
            db.execute("PRAGMA busy_timeout=15000")
            db.execute("PRAGMA foreign_keys=ON")
            self._thread_local.connection = db
        return db

    def _init_sync(self):
        db = self._connect()
        try:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    repeat_mode INTEGER DEFAULT 1,
                    language TEXT DEFAULT 'ru'
                )
                """
            )

            db.execute(
                """
                CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id TEXT NOT NULL,
                    caption TEXT,
                    category TEXT DEFAULT 'kids',
                    source TEXT DEFAULT 'admin'
                )
                """
            )

            db.execute(
                """
                CREATE TABLE IF NOT EXISTS user_history (
                    user_id INTEGER NOT NULL,
                    video_id INTEGER NOT NULL,
                    PRIMARY KEY (user_id, video_id)
                )
                """
            )

            db.execute(
                """
                CREATE TABLE IF NOT EXISTS subscriber_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    file_id TEXT NOT NULL,
                    media_type TEXT NOT NULL DEFAULT 'document',
                    caption TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    submitted_at INTEGER NOT NULL,
                    reviewed_at INTEGER,
                    reviewed_by INTEGER,
                    video_id INTEGER
                )
                """
            )

            # Корректные миграции: language только для users,
            # caption/category только для videos.
            user_cols = {
                row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()
            }
            if "language" not in user_cols:
                db.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'ru'")
            if "repeat_mode" not in user_cols:
                db.execute("ALTER TABLE users ADD COLUMN repeat_mode INTEGER DEFAULT 1")
            if "username" not in user_cols:
                db.execute("ALTER TABLE users ADD COLUMN username TEXT")

            video_cols = {
                row[1] for row in db.execute("PRAGMA table_info(videos)").fetchall()
            }
            if "caption" not in video_cols:
                db.execute("ALTER TABLE videos ADD COLUMN caption TEXT")
            if "category" not in video_cols:
                db.execute("ALTER TABLE videos ADD COLUMN category TEXT DEFAULT 'kids'")
            if "file_id" not in video_cols:
                db.execute("ALTER TABLE videos ADD COLUMN file_id TEXT")
            if "source" not in video_cols:
                db.execute("ALTER TABLE videos ADD COLUMN source TEXT DEFAULT 'admin'")

            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_lang ON users(language)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_user ON user_history(user_id)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_video ON user_history(video_id)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_videos_category ON videos(category)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_videos_source ON videos(source)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_submissions_user_time ON subscriber_submissions(user_id, submitted_at DESC)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_submissions_status ON subscriber_submissions(status)"
            )

            db.commit()
        finally:
            db.close()
            try:
                del self._thread_local.connection
            except AttributeError:
                pass

    async def _read(self, func):
        return await asyncio.to_thread(self._read_sync, func)

    def _read_sync(self, func):
        db = self._connect()
        try:
            return func(db)
        finally:
            # Connection thread-local и остается жить для следующих запросов.
            pass

    async def _write(self, func):
        async with self.write_lock:
            return await asyncio.to_thread(self._write_sync, func)

    def _write_sync(self, func):
        db = self._connect()
        try:
            result = func(db)
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise

    async def ensure_user(self, user_id: int, username: str):
        def op(db):
            db.execute(
                """
                INSERT INTO users (user_id, username, repeat_mode, language)
                VALUES (?, ?, 1, 'ru')
                ON CONFLICT(user_id) DO UPDATE SET username = excluded.username
                """,
                (user_id, username),
            )

        await self._write(op)

    async def get_user_lang(self, user_id: int) -> str:
        def op(db):
            row = db.execute(
                "SELECT language FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row and row[0] in SUPPORTED_LANGS:
                return row[0]
            return "ru"

        return await self._read(op)

    async def set_language(self, user_id: int, lang: str):
        if lang not in SUPPORTED_LANGS:
            lang = "ru"

        def op(db):
            db.execute(
                """
                INSERT INTO users (user_id, username, repeat_mode, language)
                VALUES (?, '', 1, ?)
                ON CONFLICT(user_id) DO UPDATE SET language = excluded.language
                """,
                (user_id, lang),
            )

        await self._write(op)

    async def get_repeat_mode(self, user_id: int) -> int:
        def op(db):
            row = db.execute(
                "SELECT repeat_mode FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return int(row[0]) if row else 1

        return await self._read(op)

    async def toggle_repeat(self, user_id: int) -> int:
        def op(db):
            row = db.execute(
                "SELECT repeat_mode FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            current = int(row[0]) if row else 1
            new_mode = 0 if current == 1 else 1

            db.execute(
                """
                INSERT INTO users (user_id, username, repeat_mode, language)
                VALUES (?, '', ?, 'ru')
                ON CONFLICT(user_id) DO UPDATE SET repeat_mode = excluded.repeat_mode
                """,
                (user_id, new_mode),
            )
            return new_mode

        return await self._write(op)

    async def get_videos(self):
        def op(db):
            return db.execute(
                "SELECT id, file_id, caption, category FROM videos WHERE source = 'admin' ORDER BY id"
            ).fetchall()

        return await self._read(op)

    async def get_subscriber_videos(self):
        def op(db):
            return db.execute(
                "SELECT id, file_id, caption, category FROM videos WHERE source = 'subscriber' ORDER BY id"
            ).fetchall()

        return await self._read(op)

    async def get_video(self, video_id: int):
        def op(db):
            return db.execute(
                "SELECT id, file_id, caption, category FROM videos WHERE id = ?",
                (video_id,),
            ).fetchone()

        return await self._read(op)

    async def get_history_ids(self, user_id: int):
        def op(db):
            return {
                row[0]
                for row in db.execute(
                    "SELECT video_id FROM user_history WHERE user_id = ?",
                    (user_id,),
                ).fetchall()
            }

        return await self._read(op)

    async def add_history(self, user_id: int, video_id: int):
        def op(db):
            db.execute(
                """
                INSERT OR IGNORE INTO user_history (user_id, video_id)
                VALUES (?, ?)
                """,
                (user_id, video_id),
            )

        await self._write(op)

    async def reset_history(self, user_id: int):
        def op(db):
            db.execute(
                "DELETE FROM user_history WHERE user_id = ?",
                (user_id,),
            )

        await self._write(op)

    async def add_video(
        self,
        file_id: str,
        caption: Optional[str],
        category: str,
        source: str = "admin",
    ):
        def op(db):
            cur = db.execute(
                """
                INSERT INTO videos (file_id, caption, category, source)
                VALUES (?, ?, ?, ?)
                """,
                (file_id, caption, category, source),
            )
            return cur.lastrowid

        return await self._write(op)

    async def get_subscriber_submit_status(self, user_id: int):
        def op(db):
            row = db.execute(
                """
                SELECT id, submitted_at, status
                FROM subscriber_submissions
                WHERE user_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (user_id,),
            ).fetchone()
            return row

        return await self._read(op)

    async def create_subscriber_submission(
        self,
        user_id: int,
        username: str,
        file_id: str,
        media_type: str,
        caption: Optional[str],
    ):
        now = int(time.time())

        def op(db):
            row = db.execute(
                "SELECT submitted_at FROM subscriber_submissions WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()

            if row and now - int(row[0]) < SUBSCRIBER_VIDEO_COOLDOWN:
                remaining = SUBSCRIBER_VIDEO_COOLDOWN - (now - int(row[0]))
                return None, int(remaining)

            cur = db.execute(
                """
                INSERT INTO subscriber_submissions
                    (user_id, username, file_id, media_type, caption, status, submitted_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (user_id, username, file_id, media_type, caption, now),
            )
            return cur.lastrowid, 0

        return await self._write(op)

    async def get_pending_submission(self, submission_id: int):
        def op(db):
            return db.execute(
                """
                SELECT id, user_id, username, file_id, media_type, caption, submitted_at, status
                FROM subscriber_submissions WHERE id = ?
                """,
                (submission_id,),
            ).fetchone()

        return await self._read(op)

    async def moderate_submission(self, submission_id: int, admin_id: int, decision: str, category: Optional[str] = None):
        now = int(time.time())

        def op(db):
            row = db.execute(
                """
                SELECT id, user_id, username, file_id, media_type, caption, status
                FROM subscriber_submissions WHERE id = ?
                """,
                (submission_id,),
            ).fetchone()

            if not row:
                return {"ok": False, "reason": "not_found"}
            if row[6] != "pending":
                return {"ok": False, "reason": "already", "status": row[6]}

            if decision == "approve":
                if category not in {"kids", "porno"}:
                    return {"ok": False, "reason": "category"}
                cur = db.execute(
                    """
                    INSERT INTO videos (file_id, caption, category, source)
                    VALUES (?, ?, ?, 'subscriber')
                    """,
                    (row[3], row[5], category),
                )
                video_id = cur.lastrowid
                db.execute(
                    """
                    UPDATE subscriber_submissions
                    SET status='approved', reviewed_at=?, reviewed_by=?, video_id=?
                    WHERE id=? AND status='pending'
                    """,
                    (now, admin_id, video_id, submission_id),
                )
                return {"ok": True, "decision": "approved", "user_id": row[1], "video_id": video_id}

            db.execute(
                """
                UPDATE subscriber_submissions
                SET status='rejected', reviewed_at=?, reviewed_by=?
                WHERE id=? AND status='pending'
                """,
                (now, admin_id, submission_id),
            )
            return {"ok": True, "decision": "rejected", "user_id": row[1], "video_id": None}

        return await self._write(op)

    async def delete_video(self, video_id: int):
        def op(db):
            db.execute("DELETE FROM videos WHERE id = ?", (video_id,))
            db.execute(
                "DELETE FROM user_history WHERE video_id = ?",
                (video_id,),
            )

        await self._write(op)

    async def get_stats(self):
        def op(db):
            users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            videos = db.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
            history = db.execute("SELECT COUNT(*) FROM user_history").fetchone()[0]
            return users, videos, history

        return await self._read(op)

    async def get_video_page(self, page: int, per_page: int = 5):
        offset = max(0, page) * per_page

        def op(db):
            total = db.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
            rows = db.execute(
                """
                SELECT id, caption, category
                FROM videos
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (per_page, offset),
            ).fetchall()
            return total, rows

        return await self._read(op)


db = Database(DB_PATH)

# Кэш видео. Он обновляется при добавлении/удалении и при старте.
VIDEO_CACHE = []
VIDEO_CACHE_BY_CATEGORY = {
    "kids": [],
    "porno": [],
}
SUBSCRIBER_VIDEO_CACHE = []


async def refresh_video_cache():
    global VIDEO_CACHE, VIDEO_CACHE_BY_CATEGORY, SUBSCRIBER_VIDEO_CACHE

    rows = await db.get_videos()
    subscriber_rows = await db.get_subscriber_videos()
    VIDEO_CACHE = list(rows)
    SUBSCRIBER_VIDEO_CACHE = list(subscriber_rows)

    VIDEO_CACHE_BY_CATEGORY = {
        "kids": [],
        "porno": [],
    }

    for row in VIDEO_CACHE:
        if row[3] in VIDEO_CACHE_BY_CATEGORY:
            VIDEO_CACHE_BY_CATEGORY[row[3]].append(row)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

async def ensure_user_from_message(message: Message):
    user = message.from_user
    username = user.username or "Без юзернейма"
    await db.ensure_user(user.id, username)


async def ensure_user_from_callback(callback: CallbackQuery):
    user = callback.from_user
    username = user.username or "Без юзернейма"
    await db.ensure_user(user.id, username)


def safe_caption(caption: Optional[str]) -> Optional[str]:
    if not caption:
        return None

    # Telegram caption с HTML должен получать экранированный пользовательский текст.
    # Сначала экранируем, затем режем результат: HTML escaping может увеличить длину.
    return html.escape(caption)[:MAX_CAPTION_LENGTH]


def choose_video(candidates, watched_ids):
    if not candidates:
        return None

    if not watched_ids:
        return random.choice(candidates)

    # Быстрый путь: при небольшой истории не строим полный список.
    attempts = min(20, len(candidates))
    for _ in range(attempts):
        candidate = random.choice(candidates)
        if candidate[0] not in watched_ids:
            return candidate

    # Если пользователь посмотрел почти всё, один проход над кэшем
    # дешевле бесконечных случайных попыток.
    available = [v for v in candidates if v[0] not in watched_ids]
    if available:
        return random.choice(available)

    return None


async def schedule_delete(bot: Bot, chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        # Сообщение мог удалить пользователь/Telegram или оно могло исчезнуть
        # после перезапуска. Это не критичная ошибка.
        pass


async def send_video_message(
    bot: Bot,
    message: Message,
    video_row,
    lang: str,
):
    video_id, file_id, caption, category = video_row

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎬 Еще видео",
                    callback_data=(
                        "watch_subscriber" if category == "__subscriber__"
                        else f"next_v_{category}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 Главное меню",
                    callback_data="main_menu_fixed",
                )
            ],
        ]
    )

    # answer_document оставлен намеренно: база может содержать Telegram documents.
    # supports_streaming здесь НЕ используется.
    sent_video = await message.answer_document(
        document=file_id,
        caption=safe_caption(caption),
        parse_mode="HTML",
        reply_markup=keyboard,
    )

    asyncio.create_task(
        schedule_delete(
            bot,
            message.chat.id,
            sent_video.message_id,
            10,
        )
    )

    t = get_texts(lang)
    warn_msg = await message.answer(
        text=t["video_deleted_warn"],
        parse_mode="HTML",
    )

    asyncio.create_task(
        schedule_delete(
            bot,
            message.chat.id,
            warn_msg.message_id,
            25,
        )
    )

    return sent_video


async def deliver_video(
    message: Message,
    user_id: int,
    category: Optional[str],
    lang: str,
):
    """
    Главная функция выдачи видео.

    Она используется и кнопками, и /random, поэтому больше нет fake CallbackQuery.
    """
    async with _user_locks[user_id]:
        now = time.monotonic()
        previous = _last_video_request.get(user_id, 0.0)

        if now - previous < VIDEO_COOLDOWN:
            return False, "cooldown"

        _last_video_request[user_id] = now
        if len(_last_video_request) > 10000:
            cutoff = now - 120.0
            for uid, ts in list(_last_video_request.items()):
                if ts < cutoff:
                    _last_video_request.pop(uid, None)

        repeat_mode = await db.get_repeat_mode(user_id)

        if category == "__subscriber__":
            candidates = SUBSCRIBER_VIDEO_CACHE
        elif category:
            candidates = VIDEO_CACHE_BY_CATEGORY.get(category, [])
        else:
            candidates = VIDEO_CACHE

        if not candidates:
            return False, "empty"

        watched_ids = set()

        if repeat_mode == 0:
            watched_ids = await db.get_history_ids(user_id)

        video = choose_video(candidates, watched_ids)

        if video is None and repeat_mode == 0:
            # Все ролики этой категории просмотрены — начинаем цикл заново.
            await db.reset_history(user_id)
            watched_ids = set()
            video = choose_video(candidates, watched_ids)

        if video is None:
            return False, "empty"

        # Сначала отправляем, и только после успешной отправки считаем ролик
        # просмотренным. Это устраняет ложные записи истории при ошибке Telegram API.
        await send_video_message(
            message=message,
            bot=message.bot,
            video_row=video,
            lang=lang,
        )

        if repeat_mode == 0:
            await db.add_history(user_id, video[0])

        return True, "ok"


# ============================================================
# /work /rework
# ============================================================

@router.message(Command("work"))
async def cmd_work(message: Message):
    global HEAVY_WORK_MODE

    if message.from_user.id not in ADMIN_IDS:
        return

    HEAVY_WORK_MODE = True
    await message.answer("⚠️ Режим технической сложности включен.")


@router.message(Command("rework"))
async def cmd_rework(message: Message):
    global HEAVY_WORK_MODE

    if message.from_user.id not in ADMIN_IDS:
        return

    HEAVY_WORK_MODE = False
    await message.answer("✅ Режим технической сложности выключен.")


# ============================================================
# /start
# ============================================================

@router.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject):
    await ensure_user_from_message(message)

    user_id = message.from_user.id
    args = command.args
    lang = await db.get_user_lang(user_id)
    t = get_texts(lang)
    is_admin = user_id in ADMIN_IDS

    if args and args.startswith("video_"):
        try:
            video_id = int(args.split("_", 1)[1])
        except (ValueError, TypeError):
            video_id = None

        if video_id is not None:
            video_data = await db.get_video(video_id)

            if video_data:
                try:
                    await send_video_message(
                        bot=message.bot,
                        message=message,
                        video_row=video_data,
                        lang=lang,
                    )
                    return
                except Exception:
                    logger.exception("Ошибка отправки видео по deep link")

    await message.answer(
        t["welcome"],
        reply_markup=get_user_keyboard(is_admin, lang),
        parse_mode="HTML",
    )


# ============================================================
# ГЛАВНОЕ МЕНЮ
# ============================================================

@router.callback_query(F.data == "main_menu_fixed")
async def main_menu_fixed(callback: CallbackQuery, state: FSMContext):
    await ensure_user_from_callback(callback)
    await state.clear()

    is_admin = callback.from_user.id in ADMIN_IDS
    lang = await db.get_user_lang(callback.from_user.id)
    t = get_texts(lang)

    await callback.message.answer(
        t["welcome"],
        reply_markup=get_user_keyboard(is_admin, lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "main_menu")
async def back_to_main_menu(callback: CallbackQuery, state: FSMContext):
    await ensure_user_from_callback(callback)
    await state.clear()

    is_admin = callback.from_user.id in ADMIN_IDS
    lang = await db.get_user_lang(callback.from_user.id)
    t = get_texts(lang)

    await callback.message.edit_text(
        t["welcome"],
        reply_markup=get_user_keyboard(is_admin, lang),
        parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
# ВИДЕО
# ============================================================

@router.callback_query(
    F.data.in_({"watch_kids", "watch_porno", "random_video"})
    | F.data.startswith("next_v_")
)
async def send_video_handler(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS and HEAVY_WORK_MODE:
        await callback.answer("⚠️ Бот временно перегружен.", show_alert=True)
        return

    await ensure_user_from_callback(callback)

    user_id = callback.from_user.id
    lang = await db.get_user_lang(user_id)

    category = None

    if callback.data == "watch_kids":
        category = "kids"
    elif callback.data == "watch_porno":
        category = "porno"
    elif callback.data.startswith("next_v_"):
        category = callback.data.split("_", 2)[2]
        if category not in {"kids", "porno"}:
            await callback.answer("❌ Неизвестная категория.", show_alert=True)
            return

    # Сразу убираем "часики" Telegram, не заставляя пользователя ждать.
    await callback.answer()

    try:
        success, reason = await deliver_video(
            message=callback.message,
            user_id=user_id,
            category=category,
            lang=lang,
        )

        if not success and reason == "empty":
            await callback.message.answer(
                get_texts(lang)["no_videos"],
                parse_mode="HTML",
            )
    except Exception:
        logger.exception("Ошибка выдачи видео пользователю %s", user_id)
        try:
            await callback.message.answer(
                "❌ Не удалось отправить видео. Попробуйте еще раз."
            )
        except Exception:
            pass


# ============================================================
# ВИДЕО ОТ ПОДПИСЧИКОВ
# ============================================================

@router.callback_query(F.data == "subscriber_videos")
async def subscriber_videos_menu(callback: CallbackQuery, state: FSMContext):
    await ensure_user_from_callback(callback)
    await state.clear()

    await callback.message.edit_text(
        "📹 <b>Видео от подписчиков</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "Здесь можно смотреть видео, которые прошли модерацию,\n"
        "или отправить своё видео на проверку.\n\n"
        "⏱ <b>Лимит:</b> 1 видео от одного пользователя раз в 2 часа.\n"
        "🛡 Каждое видео сначала проверяет администрация.",
        reply_markup=get_subscriber_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "add_subscriber_video")
async def add_subscriber_video_start(callback: CallbackQuery, state: FSMContext):
    await ensure_user_from_callback(callback)

    status = await db.get_subscriber_submit_status(callback.from_user.id)
    if status:
        last_submitted_at = int(status[1])
        remaining = SUBSCRIBER_VIDEO_COOLDOWN - (int(time.time()) - last_submitted_at)
        if remaining > 0:
            hours = remaining // 3600
            minutes = (remaining % 3600 + 59) // 60
            wait_text = f"{hours} ч. {minutes} мин." if hours else f"{minutes} мин."
            await callback.answer(
                f"⏳ Следующее видео можно отправить через {wait_text}.",
                show_alert=True,
            )
            return

    await state.clear()
    await state.set_state(UserStates.waiting_for_subscriber_video)

    await callback.message.edit_text(
        "📤 <b>Отправка видео</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "Отправьте одно видео следующим сообщением.\n\n"
        "⏱ Можно отправлять <b>1 видео в 2 часа</b>.\n"
        "🛡 После отправки оно попадёт на модерацию администрации.\n"
        "❌ Видео, нарушающие правила канала, будут отклонены.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="◀️ Отмена", callback_data="subscriber_videos")]]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "watch_subscriber")
async def watch_subscriber_videos(callback: CallbackQuery):
    await ensure_user_from_callback(callback)

    if not SUBSCRIBER_VIDEO_CACHE:
        await callback.answer("📭 Пока нет одобренных видео от подписчиков.", show_alert=True)
        return

    await callback.answer()
    user_id = callback.from_user.id
    lang = await db.get_user_lang(user_id)

    try:
        success, reason = await deliver_video(
            message=callback.message,
            user_id=user_id,
            category="__subscriber__",
            lang=lang,
        )
        if not success and reason == "empty":
            await callback.message.answer("📭 Пока нет одобренных видео от подписчиков.")
    except Exception:
        logger.exception("Ошибка выдачи subscriber video пользователю %s", user_id)
        await callback.message.answer("❌ Не удалось отправить видео. Попробуйте ещё раз.")


@router.message(UserStates.waiting_for_subscriber_video, F.video | F.document)
async def receive_subscriber_video(message: Message, state: FSMContext, bot: Bot):
    await ensure_user_from_message(message)

    file_id = None
    media_type = "document"
    if message.video:
        file_id = message.video.file_id
        media_type = "video"
    elif message.document:
        # Принимаем документы тоже, чтобы не ломать видео, отправленные как файл.
        file_id = message.document.file_id
        media_type = "document"

    if not file_id:
        await message.answer("❌ Отправьте именно видеофайл.")
        return

    caption = message.caption or None
    username = f"@{message.from_user.username}" if message.from_user.username else "без username"

    submission_id, remaining = await db.create_subscriber_submission(
        user_id=message.from_user.id,
        username=username,
        file_id=file_id,
        media_type=media_type,
        caption=caption,
    )

    if submission_id is None:
        minutes = (remaining + 59) // 60
        await message.answer(f"⏳ Вы уже отправляли видео. Следующее можно отправить через {minutes} мин.")
        await state.clear()
        return

    await state.clear()

    await message.answer(
        "✅ <b>Видео отправлено на модерацию!</b>\n\n"
        "Администратор проверит его. Если видео будет принято, оно появится в разделе «Видео от подписчиков».\n"
        "⏱ Следующее видео можно будет отправить через 2 часа.",
        parse_mode="HTML",
    )

    user_info = html.escape(username)
    caption_text = html.escape(caption)[:700] if caption else "без подписи"
    moderation_caption = (
        f"📥 <b>Новое видео от подписчика</b>\n"
        f"👤 {user_info} (ID: <code>{message.from_user.id}</code>)\n"
        f"🆔 Заявка: <code>{submission_id}</code>\n"
        f"📝 Подпись: {caption_text}"
    )

    for admin_id in ADMIN_IDS:
        try:
            if media_type == "video":
                await bot.send_video(
                    admin_id,
                    video=file_id,
                    caption=moderation_caption,
                    parse_mode="HTML",
                    reply_markup=get_subscriber_moderation_keyboard(submission_id),
                )
            else:
                await bot.send_document(
                    admin_id,
                    document=file_id,
                    caption=moderation_caption,
                    parse_mode="HTML",
                    reply_markup=get_subscriber_moderation_keyboard(submission_id),
                )
        except Exception:
            logger.exception("Не удалось отправить заявку %s админу %s", submission_id, admin_id)


@router.message(UserStates.waiting_for_subscriber_video)
async def subscriber_video_wrong_type(message: Message):
    await message.answer("❌ Нужно отправить именно видео. Лимит 1 видео в 2 часа.")


async def _moderate_subscriber_callback(callback: CallbackQuery, decision: str, submission_id: int, category: Optional[str] = None):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return

    result = await db.moderate_submission(
        submission_id=submission_id,
        admin_id=callback.from_user.id,
        decision=decision,
        category=category,
    )

    if not result.get("ok"):
        if result.get("reason") == "already":
            await callback.answer("ℹ️ Эта заявка уже обработана.", show_alert=True)
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            return
        await callback.answer("❌ Не удалось обработать заявку.", show_alert=True)
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    user_id = result["user_id"]
    try:
        if decision == "approve":
            await callback.bot.send_message(
                user_id,
                "🎉 <b>Ваше видео прошло модерацию!</b>\n\n"
                "Оно добавлено в раздел «Видео от подписчиков». Спасибо за отправку!",
                parse_mode="HTML",
            )
            await callback.answer("✅ Видео принято и добавлено в базу.")
        else:
            await callback.bot.send_message(
                user_id,
                "❌ <b>Ваше видео не прошло модерацию.</b>\n\n"
                "Вы сможете отправить следующее видео после окончания лимита 2 часа.",
                parse_mode="HTML",
            )
            await callback.answer("❌ Видео отклонено.")
    except Exception:
        logger.exception("Не удалось уведомить пользователя %s о модерации", user_id)
        await callback.answer("Решение сохранено, но уведомление пользователю не отправилось.", show_alert=True)

    if decision == "approve":
        await refresh_video_cache()


@router.callback_query(F.data.startswith("sub_accept_"))
async def approve_subscriber_video(callback: CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) != 4:
        await callback.answer("❌ Некорректная заявка.", show_alert=True)
        return
    try:
        submission_id = int(parts[2])
    except ValueError:
        await callback.answer("❌ Некорректная заявка.", show_alert=True)
        return
    category = parts[3]
    await _moderate_subscriber_callback(callback, "approve", submission_id, category)


@router.callback_query(F.data.startswith("sub_reject_"))
async def reject_subscriber_video(callback: CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) != 3:
        await callback.answer("❌ Некорректная заявка.", show_alert=True)
        return
    try:
        submission_id = int(parts[2])
    except ValueError:
        await callback.answer("❌ Некорректная заявка.", show_alert=True)
        return
    await _moderate_subscriber_callback(callback, "reject", submission_id)


# ============================================================
# ЯЗЫК
# ============================================================

@router.callback_query(F.data.startswith("set_lang_"))
async def set_language_callback(callback: CallbackQuery, state: FSMContext):
    await ensure_user_from_callback(callback)

    lang = callback.data.split("_", 2)[2]

    if lang not in SUPPORTED_LANGS:
        await callback.answer("❌ Неизвестный язык.", show_alert=True)
        return

    await db.set_language(callback.from_user.id, lang)
    await state.clear()

    t = get_texts(lang)
    is_admin = callback.from_user.id in ADMIN_IDS

    await callback.message.edit_text(
        t["welcome"],
        reply_markup=get_user_keyboard(is_admin, lang),
        parse_mode="HTML",
    )
    await callback.answer(t["lang_changed"])


@router.callback_query(F.data == "change_language")
async def change_language_callback(callback: CallbackQuery):
    await ensure_user_from_callback(callback)

    lang = await db.get_user_lang(callback.from_user.id)
    t = get_texts(lang)

    await callback.message.edit_text(
        t["choose_lang"],
        reply_markup=get_language_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(Command("language"))
async def cmd_language(message: Message):
    await ensure_user_from_message(message)

    lang = await db.get_user_lang(message.from_user.id)
    t = get_texts(lang)

    await message.answer(
        t["choose_lang"],
        reply_markup=get_language_keyboard(),
        parse_mode="HTML",
    )


# ============================================================
# HELP
# ============================================================

@router.message(Command("help"))
async def cmd_help(message: Message):
    await ensure_user_from_message(message)

    lang = await db.get_user_lang(message.from_user.id)
    await message.answer(
        get_texts(lang)["help_text"],
        parse_mode="HTML",
    )


@router.callback_query(F.data == "help_menu")
async def callback_help(callback: CallbackQuery):
    await ensure_user_from_callback(callback)

    lang = await db.get_user_lang(callback.from_user.id)

    await callback.message.answer(
        get_texts(lang)["help_text"],
        parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
# ОБРАТНАЯ СВЯЗЬ
# ============================================================

@router.callback_query(F.data == "contact_admin")
async def callback_contact_admin(callback: CallbackQuery, state: FSMContext):
    await ensure_user_from_callback(callback)

    await callback.message.answer(
        get_texts(
            await db.get_user_lang(callback.from_user.id)
        )["contact_text"],
        parse_mode="HTML",
    )

    await state.set_state(UserStates.waiting_for_report)
    await callback.answer()


@router.message(Command("report"))
async def cmd_report(message: Message, state: FSMContext):
    await ensure_user_from_message(message)

    lang = await db.get_user_lang(message.from_user.id)

    await message.answer(
        get_texts(lang)["report_prompt"],
        parse_mode="HTML",
    )
    await state.set_state(UserStates.waiting_for_report)


@router.message(UserStates.waiting_for_report)
async def process_report(message: Message, state: FSMContext, bot: Bot):
    report_text = message.text or message.caption or ""

    if not report_text.strip():
        await message.answer("❌ Отправьте текстовое сообщение.")
        return

    user = message.from_user

    if user.username:
        user_info = f"@{html.escape(user.username)} (ID: {user.id})"
    else:
        user_info = f"ID: {user.id}"

    safe_report = html.escape(report_text)[:3800]

    delivered = 0

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🚨 <b>Обращение от {user_info}:</b>\n{safe_report}",
                parse_mode="HTML",
            )
            delivered += 1
        except Exception:
            logger.exception("Не удалось отправить обращение админу %s", admin_id)

    lang = await db.get_user_lang(user.id)
    await message.answer(get_texts(lang)["report_sent"])
    await state.clear()

    if delivered == 0:
        logger.error("Обращение пользователя %s не доставлено ни одному админу", user.id)


@router.message(F.reply_to_message)
async def admin_reply_to_user(message: Message, bot: Bot):
    if message.from_user.id not in ADMIN_IDS:
        return

    reply_msg = message.reply_to_message

    if not reply_msg or not reply_msg.text or not message.text:
        return

    # Сохраняем совместимость со старой системой ответа по ID.
    import re

    match = re.search(r"ID:\s*(\d+)", reply_msg.text)

    if not match:
        return

    target_user_id = int(match.group(1))
    safe_reply = html.escape(message.text[:4000])

    try:
        await bot.send_message(
            target_user_id,
            f"💬 <b>Ответ администрации:</b>\n{safe_reply}",
            parse_mode="HTML",
        )
        # Не используем message.react(): это не нужно для основной логики
        # и зависит от версии aiogram/API.
    except Exception as e:
        logger.exception("Ошибка ответа пользователю %s", target_user_id)
        await message.answer(f"❌ Ошибка отправки: {e}")


# ============================================================
# /random
# ============================================================

@router.message(Command("random"))
async def cmd_random_text(message: Message):
    if HEAVY_WORK_MODE and message.from_user.id not in ADMIN_IDS:
        await message.answer("⚠️ Бот временно перегружен.")
        return

    await ensure_user_from_message(message)

    user_id = message.from_user.id
    lang = await db.get_user_lang(user_id)

    try:
        success, reason = await deliver_video(
            message=message,
            user_id=user_id,
            category=None,
            lang=lang,
        )

        if not success and reason == "empty":
            await message.answer(
                get_texts(lang)["no_videos"],
                parse_mode="HTML",
            )
    except Exception:
        logger.exception("Ошибка /random для пользователя %s", user_id)
        await message.answer("❌ Не удалось отправить видео. Попробуйте еще раз.")


# ============================================================
# НАСТРОЙКИ ПОВТОРА
# ============================================================

@router.message(Command("setting"))
async def cmd_setting(message: Message):
    await ensure_user_from_message(message)

    user_id = message.from_user.id
    lang = await db.get_user_lang(user_id)
    repeat_mode = await db.get_repeat_mode(user_id)

    await message.answer(
        get_texts(lang)["settings_title"],
        reply_markup=get_repeat_keyboard(repeat_mode, lang),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "toggle_repeat")
async def toggle_repeat_handler(callback: CallbackQuery):
    await ensure_user_from_callback(callback)

    user_id = callback.from_user.id
    lang = await db.get_user_lang(user_id)
    new_mode = await db.toggle_repeat(user_id)

    await callback.message.edit_reply_markup(
        reply_markup=get_repeat_keyboard(new_mode, lang)
    )
    await callback.answer(get_texts(lang)["settings_updated"])


# ============================================================
# FALLBACK TEXT
# ============================================================

@router.message(F.text)
async def handle_any_text(message: Message):
    if HEAVY_WORK_MODE and message.from_user.id not in ADMIN_IDS:
        await message.answer("⚠️ Бот временно перегружен.")
        return

    # Обычные сообщения не требуют ответа.
    # Важно: FSM handlers выше сработают раньше.
    return


# ============================================================
# АДМИНКА
# ============================================================

@router.callback_query(F.data == "admin_panel")
async def admin_panel_handler(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return

    await state.clear()

    await callback.message.edit_text(
        "🛠 <b>Панель администратора</b>",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return

    total_users, total_videos, total_history = await db.get_stats()

    await callback.message.edit_text(
        (
            f"📊 <b>Статистика:</b>\n"
            f"👥 Пользователей: {total_users}\n"
            f"🎬 Видео: {total_videos}\n"
            f"📚 Записей истории: {total_history}"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="◀️ Назад",
                        callback_data="admin_panel",
                    )
                ]
            ]
        ),
        parse_mode="HTML",
    )
    await callback.answer()


# ============================================================
# ДОБАВЛЕНИЕ ВИДЕО
# ============================================================

@router.callback_query(F.data == "add_video")
async def admin_add_video_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return

    await state.clear()

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🧸 Kids",
                    callback_data="category_kids",
                ),
                InlineKeyboardButton(
                    text="🔥 Porno",
                    callback_data="category_porno",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Отмена",
                    callback_data="admin_panel",
                )
            ],
        ]
    )

    await callback.message.edit_text(
        "📤 <b>Выберите категорию для загрузки видео:</b>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_for_category)
    await callback.answer()


@router.callback_query(
    AdminStates.waiting_for_category,
    F.data.startswith("category_"),
)
async def admin_get_category(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return

    category = callback.data.split("_", 1)[1]

    if category not in {"kids", "porno"}:
        await callback.answer("❌ Неизвестная категория.", show_alert=True)
        return

    await state.update_data(category=category)

    await callback.message.edit_text(
        (
            f"📤 <b>Загрузка в категорию: {html.escape(category.upper())} "
            f"(Шаг 1/2)</b>\n"
            "Отправьте видеофайл:"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="◀️ Отмена",
                        callback_data="admin_panel",
                    )
                ]
            ]
        ),
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_for_video)
    await callback.answer()


@router.message(
    AdminStates.waiting_for_video,
    F.video | F.document,
)
async def admin_get_video_file(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    file_id = None

    if message.video:
        file_id = message.video.file_id
    elif message.document:
        file_id = message.document.file_id

    if not file_id:
        await message.answer("❌ Ошибка: отправьте видеофайл.")
        return

    await state.update_data(file_id=file_id)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⏭ Пропустить подпись",
                    callback_data="skip_caption",
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Отмена",
                    callback_data="admin_panel",
                )
            ],
        ]
    )

    await message.answer(
        "📝 <b>Шаг 2/2:</b> Отправьте текст подписи к этому видео:",
        reply_markup=keyboard,
        parse_mode="HTML",
    )

    await state.set_state(AdminStates.waiting_for_caption)


@router.message(AdminStates.waiting_for_caption, F.text)
async def admin_save_video_with_caption(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    data = await state.get_data()

    file_id = data.get("file_id")
    category = data.get("category", "kids")
    caption = message.text or ""

    if not file_id:
        await state.clear()
        await message.answer("❌ Данные загрузки потеряны. Начните заново.")
        return

    if category not in {"kids", "porno"}:
        category = "kids"

    # Сохраняем обычный текст без HTML.
    caption = caption[:MAX_CAPTION_LENGTH]

    await db.add_video(
        file_id=file_id,
        caption=caption,
        category=category,
    )

    await refresh_video_cache()

    lang = await db.get_user_lang(message.from_user.id)
    is_admin = message.from_user.id in ADMIN_IDS

    await message.answer(
        "✅ Видео с подписью успешно добавлено в базу!",
        reply_markup=get_user_keyboard(is_admin, lang),
        parse_mode="HTML",
    )

    await state.clear()


@router.callback_query(
    AdminStates.waiting_for_caption,
    F.data == "skip_caption",
)
async def admin_save_video_no_caption(
    callback: CallbackQuery,
    state: FSMContext,
):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return

    data = await state.get_data()

    file_id = data.get("file_id")
    category = data.get("category", "kids")

    if not file_id:
        await state.clear()
        await callback.answer("❌ Данные загрузки потеряны.", show_alert=True)
        return

    if category not in {"kids", "porno"}:
        category = "kids"

    await db.add_video(
        file_id=file_id,
        caption=None,
        category=category,
    )

    await refresh_video_cache()

    lang = await db.get_user_lang(callback.from_user.id)
    is_admin = callback.from_user.id in ADMIN_IDS

    await callback.message.edit_text(
        "✅ Видео успешно добавлено (без подписи)!"
    )

    await callback.message.answer(
        "Главное меню:",
        reply_markup=get_user_keyboard(is_admin, lang),
    )

    await state.clear()
    await callback.answer()


# ============================================================
# УПРАВЛЕНИЕ ВИДЕО
# ============================================================

@router.callback_query(F.data.startswith("manage_videos_"))
async def manage_videos(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return

    try:
        page = max(0, int(callback.data.split("_", 2)[2]))
    except (ValueError, IndexError):
        page = 0

    per_page = 5
    total, rows = await db.get_video_page(page, per_page)

    if total == 0:
        await callback.message.edit_text(
            "📭 В базе нет видео.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="◀️ Назад",
                            callback_data="admin_panel",
                        )
                    ]
                ]
            ),
        )
        await callback.answer()
        return

    # Если админ удалил последние видео на странице, возвращаемся на последнюю.
    max_page = max(0, (total - 1) // per_page)
    if page > max_page:
        page = max_page
        total, rows = await db.get_video_page(page, per_page)

    keyboard = []

    for v_id, v_cap, v_cat in rows:
        # В кнопке не используем HTML, поэтому экранирование здесь не нужно.
        short_cap = (v_cap or "").replace("\n", " ")
        if len(short_cap) > 15:
            short_cap = short_cap[:15] + "..."

        cap_text = f" — {short_cap}" if short_cap else ""

        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"[{v_cat}] #{v_id}{cap_text}",
                    callback_data=f"v_info_{v_id}_{page}",
                )
            ]
        )

    nav = []

    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"manage_videos_{page - 1}",
            )
        )

    if (page + 1) * per_page < total:
        nav.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"manage_videos_{page + 1}",
            )
        )

    if nav:
        keyboard.append(nav)

    keyboard.append(
        [
            InlineKeyboardButton(
                text="◀️ Назад",
                callback_data="admin_panel",
            )
        ]
    )

    await callback.message.edit_text(
        f"🗑 <b>Управление видео (Всего: {total})</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("v_info_"))
async def video_info_handler(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return

    parts = callback.data.split("_")

    if len(parts) != 4:
        await callback.answer("❌ Некорректные данные.", show_alert=True)
        return

    try:
        v_id = int(parts[2])
        page = max(0, int(parts[3]))
    except ValueError:
        await callback.answer("❌ Некорректные данные.", show_alert=True)
        return

    row = await db.get_video(v_id)

    if not row:
        await callback.answer("❌ Не найдено.", show_alert=True)
        return

    _, _, cap, cat = row

    safe_cap = html.escape(cap) if cap else "Нет"
    safe_cat = html.escape(cat or "unknown")

    link = f"https://t.me/{BOT_USERNAME}?start=video_{v_id}"

    await callback.message.edit_text(
        (
            f"🎬 <b>Видео #{v_id}</b>\n"
            f"📂 Категория: <b>{safe_cat}</b>\n"
            f"📝 Подпись: {safe_cap}\n\n"
            f"🔗 <code>{html.escape(link)}</code>"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🗑 Удалить",
                        callback_data=f"del_video_{v_id}_{page}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="◀️ Назад",
                        callback_data=f"manage_videos_{page}",
                    )
                ],
            ]
        ),
        parse_mode="HTML",
    )

    await callback.answer()


@router.callback_query(F.data.startswith("del_video_"))
async def delete_video_handler(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return

    parts = callback.data.split("_")

    if len(parts) != 4:
        await callback.answer("❌ Некорректные данные.", show_alert=True)
        return

    try:
        v_id = int(parts[2])
        page = max(0, int(parts[3]))
    except ValueError:
        await callback.answer("❌ Некорректные данные.", show_alert=True)
        return

    await db.delete_video(v_id)
    await refresh_video_cache()

    await callback.answer(
        f"✅ Видео #{v_id} удалено!",
        show_alert=True,
    )

    # Не мутируем callback.data вручную — вызываем отдельный рендер страницы.
    total, rows = await db.get_video_page(page, 5)

    if total == 0:
        await callback.message.edit_text(
            "📭 В базе нет видео.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="◀️ Назад",
                            callback_data="admin_panel",
                        )
                    ]
                ]
            ),
        )
        return

    max_page = max(0, (total - 1) // 5)
    if page > max_page:
        page = max_page
        total, rows = await db.get_video_page(page, 5)

    keyboard = []

    for row in rows:
        v_id2, v_cap, v_cat = row
        short_cap = (v_cap or "").replace("\n", " ")
        if len(short_cap) > 15:
            short_cap = short_cap[:15] + "..."

        cap_text = f" — {short_cap}" if short_cap else ""

        keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"[{v_cat}] #{v_id2}{cap_text}",
                    callback_data=f"v_info_{v_id2}_{page}",
                )
            ]
        )

    nav = []

    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"manage_videos_{page - 1}",
            )
        )

    if (page + 1) * 5 < total:
        nav.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"manage_videos_{page + 1}",
            )
        )

    if nav:
        keyboard.append(nav)

    keyboard.append(
        [
            InlineKeyboardButton(
                text="◀️ Назад",
                callback_data="admin_panel",
            )
        ]
    )

    await callback.message.edit_text(
        f"🗑 <b>Управление видео (Всего: {total})</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML",
    )


# ============================================================
# BOT / FASTAPI / WEBHOOK
# ============================================================

if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

bot = Bot(token=TOKEN)
dp = Dispatcher()
dp.include_router(router)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await refresh_video_cache()

        webhook_kwargs = {
            "url": WEBHOOK_URL,
            "drop_pending_updates": True,
        }

        if WEBHOOK_SECRET:
            webhook_kwargs["secret_token"] = WEBHOOK_SECRET

        await bot.set_webhook(**webhook_kwargs)

        logger.info(
            "✅ Вебхук установлен. Видео в кэше: %s",
            len(VIDEO_CACHE),
        )

        await bot.set_my_commands(
            [
                BotCommand(
                    command="random",
                    description="🎬 Случайное видео",
                ),
                BotCommand(
                    command="setting",
                    description="⚙️ Настройки повтора",
                ),
                BotCommand(
                    command="language",
                    description="🌍 Сменить язык",
                ),
                BotCommand(
                    command="report",
                    description="💬 Связь с админом",
                ),
                BotCommand(
                    command="help",
                    description="🆘 Справка",
                ),
            ]
        )

    except Exception:
        logger.exception("❌ Ошибка запуска бота")

    yield

    await bot.session.close()


app = FastAPI(lifespan=lifespan)


@app.post(WEBHOOK_PATH)
async def bot_webhook(request: Request):
    try:
        if WEBHOOK_SECRET:
            received_secret = request.headers.get(
                "X-Telegram-Bot-Api-Secret-Token"
            )

            if received_secret != WEBHOOK_SECRET:
                return {"status": "forbidden"}

        update = Update.model_validate(
            await request.json(),
            context={"bot": bot},
        )

        await dp.feed_update(bot, update)

    except Exception:
        # traceback намного полезнее простой строки ошибки:
        logger.exception("❌ Ошибка обработки Telegram update")

    return {"status": "ok"}


@app.get("/")
@app.head("/")
async def index():
    return {"status": "Bot is alive!"}


if __name__ == "__main__":
    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=PORT,
    )
