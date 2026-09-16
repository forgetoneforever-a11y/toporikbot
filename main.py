from contextlib import asynccontextmanager
from aiogram import Bot, Dispatcher
from aiogram.types import Update, BotCommand
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import os
import uvicorn

from config import TOKEN, WEBHOOK_URL, WEBHOOK_PATH, WEBHOOK_SECRET, PORT, logger, VIDEO_CACHE
from database import db, refresh_video_cache
from handlers import router

if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

bot = Bot(token=TOKEN)
dp = Dispatcher()
dp.include_router(router)

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await db.init_db()
        await refresh_video_cache()

        webhook_kwargs = {
            "url": WEBHOOK_URL,
            "drop_pending_updates": True,
        }
        if WEBHOOK_SECRET:
            webhook_kwargs["secret_token"] = WEBHOOK_SECRET

        await bot.set_webhook(**webhook_kwargs)
        logger.info("✅ Вебхук установлен. Видео в кэше: %s", len(VIDEO_CACHE))

        await bot.set_my_commands([
            BotCommand(command="random", description="🎬 Случайное видео"),
            BotCommand(command="setting", description="⚙️ Настройки повтора"),
            BotCommand(command="language", description="🌍 Сменить язык"),
            BotCommand(command="report", description="💬 Связь с админом"),
            BotCommand(command="help", description="🆘 Справка"),
        ])
    except Exception:
        logger.exception("❌ Ошибка запуска бота")

    yield
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

@app.post(WEBHOOK_PATH)
async def bot_webhook(request: Request):
    try:
        if WEBHOOK_SECRET:
            received_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if received_secret != WEBHOOK_SECRET:
                return {"status": "forbidden"}

        update = Update.model_validate(await request.json(), context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception:
        logger.exception("❌ Ошибка обработки Telegram update")

    return {"status": "ok"}

# Эндпоинт для отдачи HTML-страницы Mini App
@app.get("/webapp", response_class=HTMLResponse)
async def web_app_view():
    file_path = os.path.join("templates", "index.html")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Template not found</h1>"

@app.get("/")
@app.head("/")
async def index():
    return {"status": "Bot is alive!"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=PORT)