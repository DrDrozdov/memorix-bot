import asyncio
import os
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_NAME = "memory.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def save_memory(user_id: int, username: str | None, text: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO memories (user_id, username, text, created_at)
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        username,
        text,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    conn.commit()
    conn.close()


def get_recent_memories(user_id: int, limit: int = 5):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT text, created_at
        FROM memories
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (user_id, limit))

    rows = cursor.fetchall()
    conn.close()

    return rows


def search_memories(user_id: int, query: str, limit: int = 10):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT text, created_at
        FROM memories
        WHERE user_id = ?
        AND LOWER(text) LIKE LOWER(?)
        ORDER BY id DESC
        LIMIT ?
    """, (
        user_id,
        f"%{query}%",
        limit
    ))

    rows = cursor.fetchall()
    conn.close()

    return rows


@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer(
        "👋 Привет! Я Remindly — твоя вторая память для Telegram.\n\n"
        "Отправь мне любой текст, мысль, ссылку или пересланное сообщение — я сохраню это.\n\n"
        "Команды:\n"
        "/memory — показать последние сохранения\n"
        "/search запрос — найти сохранения"
    )


@dp.message(Command("memory"))
async def memory_handler(message: Message):
    memories = get_recent_memories(message.from_user.id)

    if not memories:
        await message.answer("Пока ничего не сохранено. Отправь мне первый текст.")
        return

    response = "🧠 Последние сохранения:\n\n"

    for index, (text, created_at) in enumerate(memories, start=1):
        short_text = text[:300]

        if len(text) > 300:
            short_text += "..."

        response += f"{index}. {short_text}\n"
        response += f"   🕒 {created_at}\n\n"

    await message.answer(response)


@dp.message(Command("search"))
async def search_handler(message: Message):
    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer(
            "Напиши запрос после команды.\n\n"
            "Пример:\n"
            "/search ГЧП"
        )
        return

    query = parts[1].strip()
    results = search_memories(message.from_user.id, query)

    if not results:
        await message.answer(
            f"Ничего не нашёл по запросу: «{query}».\n\n"
            "Пока поиск работает по точному совпадению слов. "
            "Позже добавим смысловой AI-поиск."
        )
        return

    response = f"🔎 Нашёл по запросу: «{query}»\n\n"

    for index, (text, created_at) in enumerate(results, start=1):
        short_text = text[:300]

        if len(text) > 300:
            short_text += "..."

        response += f"{index}. {short_text}\n"
        response += f"   🕒 {created_at}\n\n"

    await message.answer(response)


@dp.message()
async def save_text_handler(message: Message):
    if not message.text:
        await message.answer("Пока я умею сохранять только текст. Файлы и голосовые добавим позже.")
        return

    save_memory(
        user_id=message.from_user.id,
        username=message.from_user.username,
        text=message.text
    )

    await message.answer(
        "✅ Сохранил в память.\n\n"
        "Чтобы посмотреть последние записи, напиши /memory\n"
        "Чтобы найти запись, напиши /search запрос"
    )


async def main():
    init_db()
    print("Remindly запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())