import asyncio
import os
from datetime import datetime

import psycopg2
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            username TEXT,
            text TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
    """)

    conn.commit()
    cursor.close()
    conn.close()


def save_memory(user_id: int, username: str | None, text: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO memories (user_id, username, text, created_at)
        VALUES (%s, %s, %s, %s)
    """, (
        user_id,
        username,
        text,
        datetime.now()
    ))

    conn.commit()
    cursor.close()
    conn.close()


def get_recent_memories(user_id: int, limit: int = 5):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT text, created_at
        FROM memories
        WHERE user_id = %s
        ORDER BY id DESC
        LIMIT %s
    """, (user_id, limit))

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return rows


def search_memories(user_id: int, query: str, limit: int = 10):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT text, created_at
        FROM memories
        WHERE user_id = %s
        AND text ILIKE %s
        ORDER BY id DESC
        LIMIT %s
    """, (
        user_id,
        f"%{query}%",
        limit
    ))

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return rows


def format_memory_list(memories, title: str):
    response = f"{title}\n\n"

    for index, (text, created_at) in enumerate(memories, start=1):
        short_text = text[:300]

        if len(text) > 300:
            short_text += "..."

        response += f"{index}. {short_text}\n"
        response += f"   🕒 {created_at.strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    return response


@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer(
        "👋 Привет! Я Remindly.\n\n"
        "Отправь мне текст, ссылку, заметку или пересланное сообщение — я сохраню это в твою личную память.\n\n"
        "Команды:\n"
        "/memory — последние сохранения\n"
        "/search запрос — поиск по сохранениям\n"
        "/help — помощь"
    )


@dp.message(Command("help"))
async def help_handler(message: Message):
    await message.answer(
        "Как пользоваться Remindly:\n\n"
        "1. Отправь мне любой текст, ссылку или пересланное сообщение.\n"
        "2. Я сохраню его в твою память.\n"
        "3. Чтобы посмотреть последние записи, напиши /memory.\n"
        "4. Чтобы найти нужную запись, напиши /search и запрос.\n\n"
        "Пример:\n"
        "/search договор\n\n"
        "Пока я сохраняю только текстовые сообщения. Поддержку файлов и голосовых добавим позже."
    )


@dp.message(Command("memory"))
async def memory_handler(message: Message):
    memories = get_recent_memories(message.from_user.id)

    if not memories:
        await message.answer(
            "Пока ничего не сохранено.\n\n"
            "Отправь мне текст, ссылку или пересланное сообщение — и я сохраню это."
        )
        return

    response = format_memory_list(
        memories,
        "🧠 Последние сохранения:"
    )

    await message.answer(response)


@dp.message(Command("search"))
async def search_handler(message: Message):
    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer(
            "Напиши запрос после команды.\n\n"
            "Пример:\n"
            "/search договор"
        )
        return

    query = parts[1].strip()
    results = search_memories(message.from_user.id, query)

    if not results:
        await message.answer(
            f"Ничего не найдено по запросу: «{query}»."
        )
        return

    response = format_memory_list(
        results,
        f"🔎 Результаты поиска по запросу: «{query}»"
    )

    await message.answer(response)


@dp.message()
async def save_text_handler(message: Message):
    if not message.text:
        await message.answer(
            "Пока я умею сохранять только текстовые сообщения."
        )
        return

    save_memory(
        user_id=message.from_user.id,
        username=message.from_user.username,
        text=message.text
    )

    await message.answer(
        "✅ Сохранено.\n\n"
        "Посмотреть последние записи: /memory\n"
        "Найти запись: /search запрос"
    )


async def main():
    init_db()
    print("Remindly started with PostgreSQL")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())