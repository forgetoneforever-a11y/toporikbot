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
    repeat_mode INTEGER DEFAULT 1
)
"""
)

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


# Клавиатуры
def get_user_keyboard(is_admin: bool):
    keyboard = [[InlineKeyboardButton(text="🎬 Рандом", callback_data="random_video")]]
    if is_admin:
        keyboard.append(
            [InlineKeyboardButton(text="🛠 Админ панель", callback_data="admin_panel")]
        )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_admin_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить новое видео", callback_data="add_video")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
            [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu")],
        ]
    )


# Хендлеры бота
@router.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "Без юзернейма"
    name = message.from_user.first_name

    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, repeat_mode) VALUES (?, ?, 1)",
        (user_id, username),
    )
    conn.commit()

    is_admin = user_id in ADMIN_IDS
    text = (
        f"<b>{name}</b> добрый день!\n"
        "Прочтите нашу осведомительную информацию /help!\n"
        "Это очень важный процесс!"
    )
    await message.answer(text, reply_markup=get_user_keyboard(is_admin), parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "<b>📚 Справка по командам бота:</b>\n\n"
        "/random — отправка рандомного видеоматериала\n"
        "/setting — настройки бота (вкл/выкл повторение видео)\n"
        "/report — отправить ошибку администрации\n"
        "/help — помощь и список команд"
    )
    await message.answer(help_text, parse_mode="HTML")


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
                    "Вы посмотрели все видео! Список просмотров сброшен.", show_alert=True
                )
            cursor.execute("SELECT id, file_id FROM videos")
            videos = cursor.fetchall()

        if not videos:
            msg = "В базе данных пока нет ни одного видео!"
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
    
    # Отправляем видео
    sent_message = await target_message.answer_video(
        video=file_id, reply_markup=get_user_keyboard(is_admin)
    )
    
    if isinstance(callback, CallbackQuery):
        await callback.answer()

    # Фоновая задача на удаление видео через 10 секунд и отправку уведомления
    bot_instance = callback.bot if isinstance(callback, CallbackQuery) else target_message.bot
    chat_id = target_message.chat.id

    async def delete_and_notify():
        await asyncio.sleep(10)
        try:
            # Удаляем отправленное видео
            await bot_instance.delete_message(chat_id=chat_id, message_id=sent_message.message_id)
        except Exception:
            pass  # Если пользователь сам уже удалил или истек срок
        
        # Отправляем подсказку о просмотре в избранном
        try:
            await bot_instance.send_message(
                chat_id=chat_id,
                text="💡 <b>Рекомендуем пересылать понравившиеся видео в Избранное</b>, так как это сообщение было удалено через 10 секунд!",
                parse_mode="HTML"
            )
        except Exception:
            pass

    # Запускаем задачу в фоновом режиме
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
    await callback.message.edit_text(
        "Главное меню:", reply_markup=get_user_keyboard(is_admin)
    )


@router.callback_query(F.data == "stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT user_id, username FROM users")
    all_users = cursor.fetchall()

    users_list_str = ""
    for u_id, u_name in all_users[-15:]:
        uname_display = f"@{u_name}" if u_name != "Без юзернейма" else "Без юзернейма"
        users_list_str += f"• {uname_display} (ID: <code>{u_id}</code>)\n"

    stats_text = (
        f"📊 <b>Статистика бота:</b>\n\n"
        f"👥 Всего зарегистрировано пользователей: <b>{total_users}</b>\n\n"
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


@router.callback_query(F.data == "add_video")
async def admin_add_video_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.message.answer(
        "📤 Отправьте видеоматериал (видео файлом), который хотите добавить в базу:"
    )
    await state.set_state(AdminStates.waiting_for_video)
    await callback.answer()


@router.message(AdminStates.waiting_for_video, F.video)
async def admin_save_video(message: Message, state: FSMContext):
    file_id = message.video.file_id
    cursor.execute("INSERT INTO videos (file_id) VALUES (?)", (file_id,))
    conn.commit()

    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer(
        "✅ Видео успешно добавлено в базу данных!",
        reply_markup=get_user_keyboard(is_admin),
    )
    await state.clear()


@router.message(AdminStates.waiting_for_video)
async def admin_wrong_video_type(message: Message):
    await message.answer("❌ Пожалуйста, отправьте именно видеофайл.")


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
async def index():
    return {"status": "Bot is alive!"}


if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=PORT)
