import os
import asyncio
from collections import defaultdict
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger("telegram_bot")

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
BOT_USERNAME = os.getenv("BOT_USERNAME", "my_bot")
PORT = int(os.getenv("PORT", 8000))

# Список администраторов (можно перенести в .env или БД)
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

SUPPORTED_LANGS = ["ru", "en", "uk", "kk"]

# Режим повышенной нагрузки
HEAVY_WORK_MODE = False

# Ограничения
MAX_CAPTION_LENGTH = 1000
VIDEO_COOLDOWN = 3.0
SUBSCRIBER_VIDEO_COOLDOWN = 7200  # 2 часа

# Глобальные кэши и примитивы синхронизации
VIDEO_CACHE = []
VIDEO_CACHE_BY_CATEGORY = {}
SUBSCRIBER_VIDEO_CACHE = []

_user_locks = defaultdict(asyncio.Lock)
_last_video_request = {}