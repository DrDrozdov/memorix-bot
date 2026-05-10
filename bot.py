import asyncio
import os
import tempfile
from datetime import datetime, timedelta

import psycopg2
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import (
    Message,
    BotCommand,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="🔍 Поиск"),
            KeyboardButton(text="🧠 Память")
        ],
        [
            KeyboardButton(text="📅 Сегодня"),
            KeyboardButton(text="⚙️ Помощь")
        ]
    ],
    resize_keyboard=True
)
client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url="https://api.aitunnel.ru/v1/"
)

def to_moscow_time(dt):
    return dt + timedelta(hours=3)

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


def get_last_memories_for_ai(user_id: int, limit: int = 30):
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


def ai_search(query: str, memories: str):
    prompt = f"""
Ты ищешь по личной памяти пользователя.

Запрос пользователя:
{query}

Записи памяти:
{memories}

Выбери только релевантные записи.
Ответь кратко, понятно и структурно.
Если подходящих записей нет, так и скажи.
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": "Ты помощник для поиска по личной памяти пользователя."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    return response.choices[0].message.content

def is_natural_search_query(text: str) -> bool:
    text_lower = text.lower().strip()

    search_triggers = [
        "найди",
        "поищи",
        "покажи",
        "что я сохранял",
        "что у меня есть",
        "есть ли у меня",
        "напомни, что",
        "напомни что",
        "вспомни",
        "найдешь",
        "найдёшь",
        "где у меня",
        "что было про",
        "что есть про"
    ]

    return any(trigger in text_lower for trigger in search_triggers)

def clean_search_query(text: str) -> str:
    text_lower = text.lower().strip()

    phrases_to_remove = [
        "найди",
        "поищи",
        "покажи",
        "что я сохранял",
        "что у меня есть",
        "есть ли у меня",
        "напомни, что",
        "напомни что",
        "вспомни",
        "где у меня",
        "что было про",
        "что есть про"
    ]

    query = text_lower

    for phrase in phrases_to_remove:
        query = query.replace(phrase, "")

    query = query.strip(" .,!?:;—-")

    if not query:
        return text

    return query

def format_memory_list(memories, title: str):
    response = f"{title}\n\n"

    for index, (text, created_at) in enumerate(memories, start=1):
        short_text = text[:300]

        if len(text) > 300:
            short_text += "..."

        moscow_time = to_moscow_time(created_at)

        response += f"{index}. {short_text}\n"
        response += f"   🕒 {moscow_time.strftime('%Y-%m-%d %H:%M:%S')} МСК\n\n"

    return response 


@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer(
        "👋 Привет! Я Memorix.\n\n"
        "Сохраняй мысли, идеи, ссылки, заметки и голосовые сообщения в одном месте — "
        "и находи их за секунды.\n\n"
        "Команды:\n"
        "/memory — последние сохранения\n"
        "/search запрос — поиск по памяти\n"
        "/today — сохранения за сегодня\n"
        "/help — помощь",
        reply_markup=main_keyboard
    )


@dp.message(Command("help"))
async def help_handler(message: Message):
    await message.answer(
        "🧠 Memorix — персональная AI-память в Telegram.\n\n"
        "Сохраняй:\n"
        "• мысли\n"
        "• голосовые\n"
        "• ссылки\n"
        "• идеи\n"
        "• заметки\n\n"
        "Как искать:\n"
        "• /search запрос\n"
        "• кнопка 🔍 Поиск\n"
        "• или просто напиши:\n"
        "«найди заметку про бренд»\n\n"
        "Команды:\n"
        "/memory — последние записи\n"
        "/today — сохранения за сегодня\n"
        "/search запрос — AI-поиск\n"
        "/help — помощь"
    )


@dp.message(Command("memory"))
async def memory_handler(message: Message):
    memories = get_recent_memories(message.from_user.id)

    if not memories:
        await message.answer("Пока ничего не сохранено.")
        return

    response = format_memory_list(
        memories,
        "🧠 Последние сохранения:"
    )

    await message.answer(response)


@dp.message(Command("today"))
async def today_handler(message: Message):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT text, created_at
        FROM memories
        WHERE user_id = %s
        AND DATE(created_at) = CURRENT_DATE
        ORDER BY created_at DESC
    """, (message.from_user.id,))

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    if not rows:
        await message.answer("📭 Сегодня пока ничего не сохранено.")
        return

    response = format_memory_list(
        rows,
        "📅 Сохранения за сегодня:"
    )

    await message.answer(response)


@dp.message(Command("search"))
async def search_handler(message: Message):
    query = message.text.replace("/search", "").strip()

    if not query:
        await message.answer(
            "🔎 Напиши запрос после команды.\n\n"
            "Пример:\n/search идея"
        )
        return

    rows = get_last_memories_for_ai(message.from_user.id)

    if not rows:
        await message.answer("🫥 Память пока пустая.")
        return

    memories = "\n".join([
    f"[{to_moscow_time(created_at).strftime('%Y-%m-%d %H:%M:%S')} МСК] {text}"
    for text, created_at in rows
])


    result = ai_search(query, memories)

    await message.answer(
        f"🧠 Результаты поиска\n\n{result}"
    )


@dp.message(lambda message: message.voice)
async def voice_handler(message: Message):
    status_message = await message.answer("🎙 Расшифровываю голосовое...")

    temp_path = None

    try:
        voice = message.voice
        file = await bot.get_file(voice.file_id)

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_file:
            temp_path = temp_file.name

        await bot.download_file(file.file_path, temp_path)

        with open(temp_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ru"
            )

        text = transcription.text.strip()

        if not text:
            await status_message.edit_text(
                "Не получилось распознать голосовое. Попробуй записать чуть громче."
            )
            return

        save_memory(
            user_id=message.from_user.id,
            username=message.from_user.username,
            text=text
        )

        await status_message.edit_text(
            f"✅ Голосовое сохранено:\n\n{text}"
        )

    except Exception as error:
        print(f"Voice transcription error: {error}")
        await status_message.edit_text(
            "Не получилось расшифровать голосовое. Попробуй ещё раз."
        )

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

@dp.message(lambda message: message.text == "🧠 Память")
async def memory_button_handler(message: Message):
    await memory_handler(message)


@dp.message(lambda message: message.text == "📅 Сегодня")
async def today_button_handler(message: Message):
    await today_handler(message)


@dp.message(lambda message: message.text == "⚙️ Помощь")
async def help_button_handler(message: Message):
    await help_handler(message)


@dp.message(lambda message: message.text == "🔍 Поиск")
async def search_button_handler(message: Message):
    await message.answer(
        "Напиши:\n/search твой запрос"
    )
@dp.message(lambda message: message.text and is_natural_search_query(message.text))
async def natural_search_handler(message: Message):
    query = clean_search_query(message.text)

    rows = get_last_memories_for_ai(message.from_user.id)

    if not rows:
        await message.answer("🫥 Память пока пустая.")
        return

    memories = "\n".join([
        f"[{to_moscow_time(created_at).strftime('%Y-%m-%d %H:%M:%S')} МСК] {text}"
        for text, created_at in rows
    ])

    result = ai_search(query, memories)

    await message.answer(
        f"🧠 Нашёл по запросу: «{query}»\n\n{result}"
    )
@dp.message()
async def save_text_handler(message: Message):
    if not message.text:
        await message.answer(
            "Пока поддерживаются только текст и голосовые сообщения."
        )
        return

    save_memory(
        user_id=message.from_user.id,
        username=message.from_user.username,
        text=message.text
    )

    await message.answer("✅ Сохранено.")


async def main():
    init_db()
    await bot.set_my_commands([
    BotCommand(command="memory", description="Последние сохранения"),
    BotCommand(command="search", description="AI-поиск по памяти"),
    BotCommand(command="today", description="Сохранения за сегодня"),
    BotCommand(command="help", description="Помощь")
])
    print("Memorix started | VERSION: CLEAN_HELP_FIX_001")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())