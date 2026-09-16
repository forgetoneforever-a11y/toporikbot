from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
import html

from config import ADMIN_IDS, SUBSCRIBER_VIDEO_CACHE, MAX_CAPTION_LENGTH
from database import db, refresh_video_cache
from states import UserStates
from keyboards import get_subscriber_keyboard, get_subscriber_moderation_keyboard
from texts import get_texts

router = Router()

@router.callback_query(F.data == "subscriber_videos")
async def subscriber_menu(callback: CallbackQuery):
    lang = await db.get_user_lang(callback.from_user.id)
    await callback.message.edit_text(
        "📹 <b>Видео от подписчиков</b>\nВыберите действие:",
        reply_markup=get_subscriber_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "add_subscriber_video")
async def add_subscriber_video_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.waiting_for_subscriber_video)
    await callback.message.edit_text(
        "📤 <b>Отправьте видео</b>, которое хотите предложить.\nМожете добавить описание (до 1000 символов).",
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(UserStates.waiting_for_subscriber_video, F.video)
async def process_subscriber_video(message: Message, state: FSMContext):
    file_id = message.video.file_id
    caption = message.caption or ""
    if len(caption) > MAX_CAPTION_LENGTH:
        caption = caption[:MAX_CAPTION_LENGTH]

    # Сохраняем в бд в статус pending
    await db.execute(
        "INSERT INTO subscriber_videos (user_id, file_id, caption, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
        (message.from_user.id, file_id, caption, int(message.date.timestamp()))
    )
    
    await state.clear()
    await message.answer("✅ Ваше видео отправлено на модерацию администраторам!")

    # Рассылка админам на модерацию
    row_id = await db.execute("SELECT last_insert_rowid() as id", fetch="one")
    sub_id = row_id["id"] if row_id else 0

    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_video(
                chat_id=admin_id,
                video=file_id,
                caption=f"📥 <b>Новое видео от подписчика #{sub_id}</b>\n\n{html.escape(caption)}",
                parse_mode="HTML",
                reply_markup=get_subscriber_moderation_keyboard(sub_id)
            )
        except Exception:
            pass

@router.callback_query(F.data.startswith("sub_accept_"))
async def accept_subscriber_video(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return

    parts = callback.data.split("_")
    sub_id = int(parts[2])
    category = parts[3]

    row = await db.execute("SELECT file_id, caption FROM subscriber_videos WHERE id = ?", (sub_id,), fetch="one")
    if not row:
        await callback.answer("❌ Видео не найдено.", show_alert=True)
        return

    # Добавляем в основную таблицу videos
    await db.execute(
        "INSERT INTO videos (file_id, caption, category, created_at) VALUES (?, ?, ?, ?)",
        (row["file_id"], row["caption"], category, int(callback.message.date.timestamp()))
    )
    await db.execute("UPDATE subscriber_videos SET status = 'approved' WHERE id = ?", (sub_id,))
    await refresh_video_cache()

    await callback.message.edit_caption(
        caption=f"{callback.message.caption}\n\n✅ <b>Одобрено в категорию: {category}</b>",
        parse_mode="HTML",
        reply_markup=None
    )
    await callback.answer("Видео одобрено и добавлено в базу!")

@router.callback_query(F.data.startswith("sub_reject_"))
async def reject_subscriber_video(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен.", show_alert=True)
        return

    sub_id = int(callback.data.split("_")[2])
    await db.execute("UPDATE subscriber_videos SET status = 'rejected' WHERE id = ?", (sub_id,))

    await callback.message.edit_caption(
        caption=f"{callback.message.caption}\n\n❌ <b>Отклонено</b>",
        parse_mode="HTML",
        reply_markup=None
    )
    await callback.answer("Видео отклонено.")