from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
import asyncio

from config import ADMIN_IDS
from database import db
from keyboards import get_admin_keyboard, get_user_keyboard
from states import UserStates

router = Router()

# Главный вход в админ-панель по кнопке
@router.callback_query(F.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return

    await callback.message.edit_text(
        "🛠 <b>Панель администратора</b>\n\nВыберите нужное действие:",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

# Статистика бота
@router.callback_query(F.data == "stats")
async def admin_stats_callback(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return

    # Получаем количество пользователей из БД
    users_count = await db.execute("SELECT COUNT(*) as cnt FROM users", fetch="one")
    total_users = users_count["cnt"] if users_count else 0

    # Получаем общее количество видео
    videos_count = await db.execute("SELECT COUNT(*) as cnt FROM videos", fetch="one")
    total_videos = videos_count["cnt"] if videos_count else 0

    stats_text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: <b>{total_users}</b>\n"
        f"🎬 Всего видео в базе: <b>{total_videos}</b>"
    )

    await callback.message.edit_text(
        stats_text,
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

# Заглушка для управления видео
@router.callback_query(F.data.startswith("manage_videos"))
async def manage_videos_stub(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return
    await callback.answer("Раздел управления видео в разработке", show_alert=True)


# ============================================================
# 1. РЕКЛАМА (/reklama)
# ============================================================

@router.message(Command("reklama"))
async def cmd_reklama(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Доступ запрещен.")
        return

    await state.set_state(UserStates.waiting_for_reklama_content)
    await message.answer(
        "📢 <b>Создание рекламного поста</b>\n\n"
        "Отправьте медиафайл (фото или видео/MP4) с текстом-описанием, либо просто текст.\n"
        "<i>Поддерживается HTML-разметка.</i>\n\n"
        "Для отмены отправьте /cancel",
        parse_mode="HTML"
    )

@router.message(UserStates.waiting_for_reklama_content, F.text == "/cancel")
async def cancel_reklama(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Создание рекламы отменено.")

@router.message(UserStates.waiting_for_reklama_content)
async def process_reklama_creation(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    await state.clear()
    
    # Шаблонизируем рекламный пост
    promo_badge = "\n\n📢 <b>Реклама</b>"
    
    if message.photo:
        photo_id = message.photo[-1].file_id
        caption = (message.caption or "") + promo_badge
        await message.answer_photo(
            photo=photo_id,
            caption=caption,
            parse_mode="HTML"
        )
    elif message.video:
        video_id = message.video.file_id
        caption = (message.caption or "") + promo_badge
        await message.answer_video(
            video=video_id,
            caption=caption,
            parse_mode="HTML"
        )
    elif message.text:
        text = message.text + promo_badge
        await message.answer(text, parse_mode="HTML")
    else:
        await message.answer("❌ Неподдерживаемый формат. Отправьте фото, видео или текст.")
        return

    await message.answer("✅ Рекламный пост успешно сформирован и показан выше как шаблон!")


# ============================================================
# 2. МАССОВАЯ РАССЫЛКА ВСЕМ (/all)
# ============================================================

@router.message(Command("all"))
async def cmd_broadcast(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Доступ запрещен.")
        return

    await state.set_state(UserStates.waiting_for_broadcast_content)
    await message.answer(
        "📣 <b>Массовая рассылка пользователям</b>\n\n"
        "Отправьте сообщение (текст, фото или видео), которое будет разослано <b>всем</b> зарегистрированным пользователям бота.\n"
        "Для отмены отправьте /cancel",
        parse_mode="HTML"
    )

@router.message(UserStates.waiting_for_broadcast_content, F.text == "/cancel")
async def cancel_broadcast(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Рассылка отменена.")

@router.message(UserStates.waiting_for_broadcast_content)
async def execute_broadcast(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    await state.clear()
    status_msg = await message.answer("⏳ <b>Рассылка запущена...</b>", parse_mode="HTML")

    # Получаем всех пользователей из базы данных
    users = await db.execute("SELECT user_id FROM users", fetch="all")
    if not users:
        await status_msg.edit_text("📭 В базе нет пользователей для рассылки.")
        return

    success = 0
    blocked = 0
    failed = 0

    for row in users:
        u_id = row["user_id"]
        try:
            # Безопасно копируем сообщение каждому пользователю
            await message.send_copy(chat_id=u_id)
            success += 1
        except Exception as e:
            err_str = str(e).lower()
            if "blocked" in err_str or "deactivated" in err_str:
                blocked += 1
            else:
                failed += 1
        # Пауза для обхода Flood Control от Telegram
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📤 Успешно доставлено: <b>{success}</b>\n"
        f"🚫 Заблокировали бота: <b>{blocked}</b>\n"
        f"❌ Ошибок отправки: <b>{failed}</b>",
        parse_mode="HTML"
    )