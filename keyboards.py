from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

def get_user_keyboard(is_admin: bool, lang: str) -> InlineKeyboardMarkup:
    keyboard = [
        # 1. Главная фишка: Mini App на всю ширину сверху
        [InlineKeyboardButton(text="📱 Открыть Mini App", web_app=WebAppInfo(url="https://your-domain.com/webapp"))],
        
        # 2. Основное действие (Случайное видео) отдельно
        [InlineKeyboardButton(text="🎬 Случайное видео", callback_data="random_video")],
        
        # 3. Категории в один ряд (компактно)
        [
            InlineKeyboardButton(text="👶 Kids", callback_data="watch_kids"),
            InlineKeyboardButton(text="🔞 Porno", callback_data="watch_porno")
        ],
        
        # 4. Доп. разделы по парам
        [
            InlineKeyboardButton(text="📹 От подписчиков", callback_data="subscriber_videos"),
            InlineKeyboardButton(text="💬 Связь", callback_data="report_admin") # или твой callback для связи
        ],
        
        # 5. Настройки и помощь тоже в один аккуратный ряд
        [
            InlineKeyboardButton(text="🌍 Язык", callback_data="change_language"),
            InlineKeyboardButton(text="🆘 Помощь", callback_data="help_menu")
        ]
    ]
    
    # 6. Админ-панель добавляется только для администраторов
    if is_admin:
        keyboard.append([InlineKeyboardButton(text="🛠 Админ-панель", callback_data="admin_panel")])
        
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru"),
            InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")
        ],
        [
            InlineKeyboardButton(text="🇺🇦 Українська", callback_data="set_lang_uk"),
            InlineKeyboardButton(text="🇰🇿 Қазақша", callback_data="set_lang_kk")
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu_fixed")]
    ])

def get_subscriber_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👀 Смотреть видео", callback_data="watch_subscriber")],
        [InlineKeyboardButton(text="📤 Отправить своё видео", callback_data="add_subscriber_video")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu_fixed")]
    ])

def get_subscriber_moderation_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Kids", callback_data=f"sub_accept_{submission_id}_kids"),
            InlineKeyboardButton(text="✅ Porno", callback_data=f"sub_accept_{submission_id}_porno")
        ],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"sub_reject_{submission_id}")]
    ])

def get_repeat_keyboard(repeat_mode: int, lang: str) -> InlineKeyboardMarkup:
    status_text = "🟢 Выключен (без повторов)" if repeat_mode == 0 else "🔁 Включен (возможны повторы)"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=status_text, callback_data="toggle_repeat")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu_fixed")]
    ])

def get_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="🗑 Управление видео", callback_data="manage_videos_0")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu_fixed")]
    ])