import aiosqlite
import asyncio
import time
from config import logger, VIDEO_CACHE, VIDEO_CACHE_BY_CATEGORY, SUBSCRIBER_VIDEO_CACHE

class Database:
    def __init__(self, db_path: str = "bot.db"):
        self.db_path = db_path

    async def execute(self, query: str, params: tuple = (), fetch: str = None):
        def _run():
            import sqlite3
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query, params)
                if fetch == "one":
                    return cursor.fetchone()
                if fetch == "all":
                    return cursor.fetchall()
                conn.commit()
                return cursor.lastrowid
        return await asyncio.to_thread(_run)

    async def init_db(self):
        await self.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                lang TEXT DEFAULT 'ru',
                repeat_mode INTEGER DEFAULT 0,
                created_at INTEGER
            )
        """)
        await self.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT,
                caption TEXT,
                category TEXT,
                created_at INTEGER
            )
        """)
        await self.execute("""
            CREATE TABLE IF NOT EXISTS subscriber_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                file_id TEXT,
                caption TEXT,
                status TEXT DEFAULT 'pending',
                created_at INTEGER
            )
        """)
        await self.execute("""
            CREATE TABLE IF NOT EXISTS history (
                user_id INTEGER,
                video_id INTEGER,
                watched_at INTEGER
            )
        """)
        logger.info("✅ База данных инициализирована.")

    async def ensure_user(self, user_id: int, username: str):
        user = await self.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,), fetch="one")
        if not user:
            await self.execute(
                "INSERT INTO users (user_id, username, created_at) VALUES (?, ?, ?)",
                (user_id, username, int(time.time()))
            )

    async def get_user_lang(self, user_id: int) -> str:
        res = await self.execute("SELECT lang FROM users WHERE user_id = ?", (user_id,), fetch="one")
        return res["lang"] if res else "ru"

    async def update_user_lang(self, user_id: int, lang: str):
        await self.execute("UPDATE users SET lang = ? WHERE user_id = ?", (lang, user_id))

    async def get_repeat_mode(self, user_id: int) -> int:
        res = await self.execute("SELECT repeat_mode FROM users WHERE user_id = ?", (user_id,), fetch="one")
        return res["repeat_mode"] if res else 0

    async def update_repeat_mode(self, user_id: int, mode: int):
        await self.execute("UPDATE users SET repeat_mode = ? WHERE user_id = ?", (mode, user_id))

    async def get_video(self, v_id: int):
        res = await self.execute("SELECT id, file_id, caption, category FROM videos WHERE id = ?", (v_id,), fetch="one")
        return res

    async def delete_video(self, v_id: int):
        await self.execute("DELETE FROM videos WHERE id = ?", (v_id,))

    async def get_video_page(self, page: int, per_page: int):
        offset = page * per_page
        total_row = await self.execute("SELECT COUNT(*) as cnt FROM videos", fetch="one")
        total = total_row["cnt"] if total_row else 0
        rows = await self.execute("SELECT id, caption, category FROM videos ORDER BY id DESC LIMIT ? OFFSET ?", (per_page, offset), fetch="all")
        return total, rows

db = Database()

async def refresh_video_cache():
    global VIDEO_CACHE, VIDEO_CACHE_BY_CATEGORY, SUBSCRIBER_VIDEO_CACHE
    try:
        rows = await db.execute("SELECT id, file_id, caption, category FROM videos", fetch="all")
        VIDEO_CACHE = [tuple(r) for r in rows]

        cat_dict = {}
        for row in rows:
            cat = row["category"]
            if cat not in cat_dict:
                cat_dict[cat] = []
            cat_dict[cat].append(tuple(row))
        VIDEO_CACHE_BY_CATEGORY = cat_dict

        sub_rows = await db.execute(
            "SELECT id, file_id, caption, category FROM subscriber_videos WHERE status = 'approved'",
            fetch="all"
        )
        SUBSCRIBER_VIDEO_CACHE = [tuple(r) for r in sub_rows]
        logger.info("🔄 Кэш видео обновлен. Всего: %s, Подписчиков: %s", len(VIDEO_CACHE), len(SUBSCRIBER_VIDEO_CACHE))
    except Exception:
        logger.exception("❌ Ошибка обновления кэша видео")