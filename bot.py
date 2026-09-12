import asyncio
import logging
import os
import random
import sqlite3
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
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

WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL", "https://your-app-name.onrender.com")
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

PORT = int(os.getenv("PORT", 8000))

logging.basicConfig(level=logging.INFO)
router = Router()

# Инициализация базы данных SQLite
conn = sqlite3.connect("bot_database.db", check_same_thread=False)
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

# Проверка на случай, если таблица users уже существовала без колонки language
try:
    cursor.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'ru'")
    conn.commit()
except sqlite3.OperationalError:
    pass  # Колонка уже есть

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT
)
"""
)

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS user_history (
    user_id INTEGER,
    video_id INTEGER,
    PRIMARY KEY (user_id, video_id)
)
"""
)
conn.commit()


# Состояния для FSM
class AdminStates(StatesGroup):
    waiting_for_video = State()


class UserStates(StatesGroup):
    waiting_for_report = State()


# Тексты для разных языков
LANG_TEXTS = {
    "ru": {
        "welcome": "<b>{name}</b>, добрый день!\nПрочтите нашу осведомительную информацию /help!\nЭто очень важный процесс!",
        "choose_lang": "🌍 Пожалуйста, выберите язык / Please choose your language:",
        "lang_changed": "✅ Язык успешно изменен на русский!",
        "btn_random": "🎬 Рандом",
        "btn_help": "🆘 Помощь",
        "btn_contact": "💬 Связь с админом",
        "btn_admin": "🛠 Админ панель",
        "help_text": (
            "<b>📚 Справка по командам бота:</b>\n\n"
            "/random — отправка рандомного видеоматериала\n"
            "/setting — настройки бота (вкл/выкл повторение видео)\n"
            "/language — сменить язык / Change language\n"
            "/report — отправить ошибку администрации\n"
            "/help — помощь и список команд"
        ),
        "no_videos": "В базе данных пока нет ни одного видео!",
        "video_deleted_warn": "💡 <b>Рекомендуем пересылать понравившиеся видео в Избранное</b>, так как это сообщение было удалено через 10 секунд!",
    },
    "en": {
        "welcome": "Hello <b>{name}</b>!\nPlease read our information via /help!\nThis is very important!",
        "choose_lang": "🌍 Please choose your language:",
        "lang_changed": "✅ Language successfully changed to English!",
        "btn_random": "🎬 Random",
        "btn_help": "🆘 Help",
        "btn_contact": "💬 Contact Admin",
        "btn_admin": "🛠 Admin Panel",
        "help_text": (
            "<b>📚 Bot Commands Help:</b>\n\n"
            "/random — send a random video\n"
            "/setting — bot settings (enable/disable video repeat)\n"
            "/language — change language\n"
            "/report — report an issue to administration\n"
            "/help — help and list of commands"
        ),
        "no_videos": "There are no videos in the database yet!",
        "video_deleted_warn": "💡 <b>We recommend forwarding favorite videos to Saved Messages</b>, as this message was deleted after 10 seconds!",
    },
    "uk": {
        "welcome": "Вітаємо, <b>{name}</b>!\nПрочитайте нашу інформацію за командою /help!\nЦе дуже важливий процес!",
        "choose_lang": "🌍 Будь ласка, виберіть мову:",
        "lang_changed": "✅ Мову успішно змінено на українську!",
        "btn_random": "🎬 Випадкове",
        "btn_help": "🆘 Допомога",
        "btn_contact": "💬 Зв'язок з адміном",
        "btn_admin": "🛠 Адмін панель",
        "help_text": (
            "<b>📚 Довідка по командах бота:</b>\n\n"
            "/random — відправка випадкового відео\n"
            "/setting — налаштування бота (увімк/вимк повторення відео)\n"
            "/language — змінити мову\n"
            "/report — надіслати помилку адміністрації\n"
            "/help — допомога та список команд"
        ),
        "no_videos": "У базі даних поки немає жодного відео!",
        "video_deleted_warn": "💡 <b>Рекомендуємо пересилати вподобані відео в Збережене (Обране)</b>, оскільки це повідомлення було видалено через 10 секунд!",
    },
    "kk": {
        "welcome": "Қайырлы күн, <b>{name}</b>!\n/help арқылы ақпаратпен танысыңыз!\nБұл өте маңызды процесс!",
        "choose_lang": "🌍 Тілді таңдаңыз / Please choose your language:",
        "lang_changed": "✅ Тіл қазақ тіліне сәтті ауыстырылды!",
        "btn_random": "🎬 Кездейсоқ",
        "btn_help": "🆘 Көмек",
        "btn_contact": "💬 Әкімшімен байланыс",
        "btn_admin": "🛠 Админ панель",
        "help_text": (
            "<b>📚 Бот командалары бойынша анықтама:</b>\n\n"
            "/random — кездейсоқ видео жіберу\n"
            "/setting — бот параметрлері (видео қайталауды қосу/өшіру)\n"
            "/language — тілді өзгерту\n"
            "/report — әкімшілікке қате туралы хабарлау\n"
            "/help — көмек және командалар тізімі"
        ),
        "no_videos": "Дерекқорда әзірге видеолар жоқ!",
        "video_deleted_warn": "💡 <b>Ұнаған видеоларды Таңдаулыларға (Избранное) жіберуге кеңес береміз</b>, себебі бұл хабарлама 10 секундтан кейін өшіріледі!",
    },
}


def get_user_lang(user_id: int) -> str:
    cursor.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row and row[0] in LANG_TEXTS:
        return row[0]
    return "ru"


# Клавиатура выбора языка
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


# Клавиатуры интерфейса
def get_user_keyboard(is_admin: bool, lang: str = "ru"):
    t = LANG_TEXTS.get(lang, LANG_TEXTS["ru"])
    keyboard = [
        [InlineKeyboardButton(text=t["btn_random"], callback_data="random_video")],
        [
            InlineKeyboardButton(text=t["btn_help"], callback_data="help_menu"),
            InlineKeyboardButton(text=t["btn_contact"], callback_data="contact_admin"),
        ],
        [InlineKeyboardButton(text="🌍 Изменить язык / Lang", callback_data="change_language")],
    ]
    if is_admin:
        keyboard.append(
            [InlineKeyboardButton(text=t["btn_admin"], callback_data="admin_panel")]
        )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить новое видео", callback_data="add_video")],
            [InlineKeyboardButton(text="🗑 Управление базой (Видео)", callback_data="manage_videos_0")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
            [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu")],
        ]
    )


# Хендлеры бота
@router.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "Без юзернейма"

    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, repeat_mode, language) VALUES (?, ?, 1, 'ru')",
        (user_id, username),
    )
    conn.commit()

    await message.answer(
        LANG_TEXTS["ru"]["choose_lang"],
        reply_markup=get_language_keyboard(),
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
        "🌍 Пожалуйста, выберите язык / Please choose your language:",
        reply_markup=get_language_keyboard(),
    )
    await callback.answer()


@router.message(Command("language"))
async def cmd_language(message: Message):
    await message.answer(
        "🌍 Пожалуйста, выберите язык / Please choose your language:",
        reply_markup=get_language_keyboard(),
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
    await callback.message.answer("📝 Опишите ошибку или проблему, и мы передадим её администрации:")
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
                    text=f"Повтор видео: {status_text}", callback_data="toggle_repeat"
                )
            ]
        ]
    )
    await message.answer("⚙️ <b>Настройки бота:</b>", reply_markup=keyboard, parse_mode="HTML")


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
                    text=f"Повтор видео: {status_text}", callback_data="toggle_repeat"
                )
            ]
        ]
    )
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer("Настройки обновлены!")


@router.message(Command("report"))
async def cmd_report(message: Message, state: FSMContext):
    await message.answer("📝 Опишите ошибку или проблему, и мы передадим её администрации:")
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
                f"🚨 <b>Новый репорт от {user_info}:</b>\n\n{report_text}",
                parse_mode="HTML",
            )
        except Exception:
            pass

    await message.answer("✅ Ваша ошибка успешно отправлена администрации. Спасибо!")
    await state.clear()


@router.callback_query(F.data == "random_video")
async def send_random_video(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    t = LANG_TEXTS[lang]

    cursor.execute("SELECT repeat_mode FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    repeat_mode = row[0] if row else 1

    if repeat_mode == 1:
        cursor.execute("SELECT id, file_id FROM videos")
    else:
        cursor.execute(
            """
            SELECT id, file_id FROM videos 
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
                    "Список просмотров сброшен.", show_alert=True
                )
            cursor.execute("SELECT id, file_id FROM videos")
            videos = cursor.fetchall()

        if not videos:
            msg = t["no_videos"]
            if isinstance(callback, CallbackQuery):
                await callback.answer(msg, show_alert=True)
            else:
                await callback.message.answer(msg)
            return

    video_id, file_id = random.choice(videos)

    cursor.execute(
        "INSERT OR IGNORE INTO user_history (user_id, video_id) VALUES (?, ?)",
        (user_id, video_id),
    )
    conn.commit()

    is_admin = user_id in ADMIN_IDS
    target_message = callback.message if isinstance(callback, CallbackQuery) else callback
    
    sent_message = await target_message.answer_document(
        document=file_id, 
        supports_streaming=True, 
        reply_markup=get_user_keyboard(is_admin, lang)
    )
    
    if isinstance(callback, CallbackQuery):
        await callback.answer()

    bot_instance = callback.bot if isinstance(callback, CallbackQuery) else target_message.bot
    chat_id = target_message.chat.id

    async def delete_and_notify():
        await asyncio.sleep(10)
        try:
            await bot_instance.delete_message(chat_id=chat_id, message_id=sent_message.message_id)
        except Exception:
            pass
        
        try:
            await bot_instance.send_message(
                chat_id=chat_id,
                text=t["video_deleted_warn"],
                parse_mode="HTML"
            )
        except Exception:
            pass

    asyncio.create_task(delete_and_notify())


@router.callback_query(F.data == "admin_panel")
async def admin_panel_handler(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к этой панели.", show_alert=True)
        return
    await callback.message.edit_text(
        "🛠 <b>Админ-панель</b>\nВыберите действие:",
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
    for u_id, u_name in all_users[-15:]:
        uname_display = f"@{u_name}" if u_name != "Без юзернейма" else "Без юзернейма"
        users_list_str += f"• {uname_display} (ID: <code>{u_id}</code>)\n"

    stats_text = (
        f"📊 <b>Статистика бота:</b>\n\n"
        f"👥 Всего пользователей: <b>{total_users}</b>\n"
        f"🎬 Всего видео в базе: <b>{total_videos}</b>\n\n"
        f"<b>Последние пользователи:</b>\n{users_list_str}"
    )
    await callback.message.edit_text(
        stats_text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад в админку", callback_data="admin_panel")]
            ]
        ),
        parse_mode="HTML",
    )


# Управление базой видео (список с кнопками удаления и пагинацией)
@router.callback_query(F.data.startswith("manage_videos_"))
async def manage_videos(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return

    page = int(callback.data.split("_")[2])
    per_page = 5

    cursor.execute("SELECT id FROM videos ORDER BY id DESC")
    all_videos = cursor.fetchall()
    total_videos = len(all_videos)

    if total_videos == 0:
        await callback.message.edit_text(
            "📭 В базе данных пока нет ни одного видео.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад в админку", callback_data="admin_panel")]
                ]
            ),
        )
        await callback.answer()
        return

    start_idx = page * per_page
    end_idx = start_idx + per_page
    page_videos = all_videos[start_idx:end_idx]

    keyboard = []
    for (v_id,) in page_videos:
        keyboard.append([InlineKeyboardButton(text=f"🗑 Удалить видео #{v_id}", callback_data=f"del_video_{v_id}_{page}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"manage_videos_{page - 1}"))
    if end_idx < total_videos:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"manage_videos_{page + 1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton(text="◀️ Назад в админку", callback_data="admin_panel")])

    await callback.message.edit_text(
        f"🗑 <b>Управление базой видео</b>\nВсего видео в базе: <b>{total_videos}</b>\nВыберите видео для удаления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )
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
    await callback.message.answer(
        "📤 Отправьте видеоматериалы (можно сразу несколько файлов или видео, сжатые и несжатые), которые хотите добавить в базу:"
    )
    await state.set_state(AdminStates.waiting_for_video)
    await callback.answer()


@router.message(AdminStates.waiting_for_video, F.video | F.document)
async def admin_save_video(message: Message, state: FSMContext):
    file_id = None
    if message.video:
        file_id = message.video.file_id
    elif message.document:
        if message.document.mime_type and "video" in message.document.mime_type:
            file_id = message.document.file_id
        elif message.document.file_name and message.document.file_name.lower().endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm')):
            file_id = message.document.file_id

    if file_id:
        cursor.execute("INSERT INTO videos (file_id) VALUES (?)", (file_id,))
        conn.commit()

        is_admin = message.from_user.id in ADMIN_IDS
        lang = get_user_lang(message.from_user.id)
        await message.answer(
            "✅ Видео успешно добавлено в базу данных!",
            reply_markup=get_user_keyboard(is_admin, lang),
        )
        await state.clear()
    else:
        await message.answer("❌ Этот файл не похож на видео. Пожалуйста, отправьте видеофайл.")


@router.message(AdminStates.waiting_for_video)
async def admin_wrong_video_type(message: Message):
    await message.answer("❌ Пожалуйста, отправьте видео или видеофайл.")


# Инициализация FastAPI и Aiogram для Web Service
app = FastAPI()
bot = Bot(token=TOKEN)
dp = Dispatcher()
dp.include_router(router)


@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Webhook успешно установлен на: {WEBHOOK_URL}")


@app.on_event("shutdown")
async def on_shutdown():
    await bot.session.close()


@app.post(WEBHOOK_PATH)
async def bot_webhook(request: Request):
    from aiogram.types import Update
    update_data = await request.json()
    update = Update.model_validate(update_data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"status": "ok"}


@app.get("/")
@app.head("/")
async def index():
    return {"status": "Bot is alive!"}


if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=PORT)
