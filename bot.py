import asyncio
import os
import tempfile
from urllib.parse import urlparse
import json
import re
import html
from datetime import datetime, timedelta

import psycopg2
from aiogram import Bot, Dispatcher
from aiogram.filters import Command

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from aiogram.types import (
    Message,
    BotCommand,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
media_group_buffer = {}
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="🔍 Поиск"),
            KeyboardButton(text="🧠 Память")
        ],
        [
            KeyboardButton(text="📅 Сегодня"),
            KeyboardButton(text="⚙️ Помощь")
        ],
        [
            KeyboardButton(text="📌 Закреплённые"),
            KeyboardButton(text="🏷 Теги")
        ],
        [
            KeyboardButton(text="📂 Категории")
        ],
        [
            KeyboardButton(text="🧩 Типы контента")
        ]
    ],
    resize_keyboard=True
)
client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url="https://api.aitunnel.ru/v1/"
)

class EditMemoryState(StatesGroup):
    waiting_for_text = State()

class EditCategoryState(StatesGroup):
    waiting_for_category = State()

class EditTagsState(StatesGroup):
    waiting_for_tags = State()

def to_moscow_time(dt):
    return dt + timedelta(hours=3)

def detect_content_type(text: str) -> str:
    text_lower = text.lower()

    if "http://" in text_lower or "https://" in text_lower or "www." in text_lower:
        return "🔗 ссылка"

    return "📝 текст"


def generate_memory_metadata(text: str):
    content_type = detect_content_type(text)

    prompt = f"""
Проанализируй запись пользователя и верни метаданные для системы личной памяти.

Запись:
{text}

Выбери одну категорию строго из списка:
💼 Работа
📚 Учёба
🚗 Авто
💰 Финансы
🎨 Дизайн
💻 Техника
🧠 Идеи
🏠 Быт
🔒 Приватное
🔗 Материалы
📦 Разное

Правила:
- category — только одна категория из списка;
- content_type уже определён как: {content_type};
- tags — 2–5 коротких тегов на русском;
- теги без пробелов, без # внутри JSON;
- не придумывай факты, которых нет в записи;
- если запись содержит ссылку, чаще всего выбирай 🔗 Материалы, если нет более точной категории;
- если запись личная, приватная, про планы, отношения, здоровье, внутренние мысли — выбирай 🔒 Приватное;
- если запись не подходит никуда — выбирай 📦 Разное;
- не используй имена людей как теги;
- теги должны отражать тему и смысл записи, а не конкретных людей;
- если в тексте есть имя человека — не превращай его в тег.

Верни строго JSON:
{{
  "category": "🚗 Авто",
  "content_type": "{content_type}",
  "tags": ["покупка", "расходы", "ауди"]
}}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Ты классификатор заметок. Возвращай только валидный JSON."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        content = response.choices[0].message.content.strip()
        metadata = json.loads(content)

        allowed_categories = [
            "💼 Работа",
            "📚 Учёба",
            "🚗 Авто",
            "💰 Финансы",
            "🎨 Дизайн",
            "💻 Техника",
            "🧠 Идеи",
            "🏠 Быт",
            "🔒 Приватное",
            "🔗 Материалы",
            "📦 Разное"
        ]

        category = metadata.get("category", "📦 Разное")

        if category not in allowed_categories:
            category = "📦 Разное"

        tags = metadata.get("tags", [])

        if not isinstance(tags, list):
            tags = []

        tags = [
            str(tag).lower().strip().replace("#", "").replace(" ", "_")
            for tag in tags
            if str(tag).strip()
        ][:5]

        if not tags:
            tags = ["разное"]

        return {
            "category": category,
            "content_type": content_type,
            "tags": tags
        }

    except Exception as error:
        print(f"Metadata generation error: {error}")

        return {
            "category": "🔗 Материалы" if content_type == "🔗 ссылка" else "📦 Разное",
            "content_type": content_type,
            "tags": ["разное"]
        }

def get_save_title(content_type):
    content_type = str(content_type).lower().strip()

    mapping = {
        "text": "✅ Добавлено в память",
        "текст": "✅ Добавлено в память",
        "📝 текст": "✅ Добавлено в память",

        "link": "🔗 Ссылка сохранена",
        "url": "🔗 Ссылка сохранена",
        "ссылка": "🔗 Ссылка сохранена",
        "🔗 ссылка": "🔗 Ссылка сохранена",

        "voice": "🎙 Голосовое сохранено",
        "audio": "🎙 Голосовое сохранено",
        "голосовое": "🎙 Голосовое сохранено",
        "🎙 голосовое": "🎙 Голосовое сохранено",

        "idea": "💡 Идея сохранена",
        "идея": "💡 Идея сохранена",
        "💡 идея": "💡 Идея сохранена",

        "photo": "🖼 Фото сохранено",
        "фото": "🖼 Фото сохранено",
        "🖼 фото": "🖼 Фото сохранено",

        "video_note": "⭕ Кружок сохранён",
        "кружок": "⭕ Кружок сохранён",
        "⭕ кружок": "⭕ Кружок сохранён",

        "video": "🎬 Видео сохранено",
        "видео": "🎬 Видео сохранено",
        "🎬 видео": "🎬 Видео сохранено",
    }

    return mapping.get(
        content_type,
        "✅ Добавлено в память"
    )

def make_preview(text: str, limit: int = 120):
    if not text:
        return ""

    clean_text = " ".join(text.split())

    if len(clean_text) > limit:
        clean_text = clean_text[:limit].rstrip() + "..."

    return clean_text

def extract_forward_source(message: Message):
    source_title = None
    source_username = None
    source_chat_id = None
    source_link = None

    origin = getattr(message, "forward_origin", None)

    if origin:
        chat = getattr(origin, "chat", None)

        if chat:
            source_title = getattr(chat, "title", None)
            source_username = getattr(chat, "username", None)
            source_chat_id = getattr(chat, "id", None)

    old_chat = getattr(message, "forward_from_chat", None)

    if old_chat:
        source_title = getattr(old_chat, "title", source_title)
        source_username = getattr(old_chat, "username", source_username)
        source_chat_id = getattr(old_chat, "id", source_chat_id)

    if source_username:
        source_link = f"https://t.me/{source_username}"

    return {
        "source_title": source_title,
        "source_username": source_username,
        "source_chat_id": source_chat_id,
        "source_link": source_link
    }

def extract_domain(text: str):
    if not text:
        return ""

    words = text.split()

    for word in words:
        if word.startswith("http://") or word.startswith("https://"):
            parsed = urlparse(word)
            return parsed.netloc.replace("www.", "")

    return ""

def format_tags(tags):
    if not tags:
        return ""

    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = [tags]

    if not isinstance(tags, list):
        tags = [str(tags)]

    clean_tags = []

    for tag in tags:
        tag = str(tag).strip().lower()
        tag = tag.replace(" ", "").replace("-", "")

        if tag and tag not in clean_tags:
            clean_tags.append(tag)

    limited_tags = clean_tags[:3]

    if not limited_tags:
        return ""

    return " ".join(f"#{tag}" for tag in limited_tags)

def get_after_edit_keyboard(memory_id: int, pinned: bool = False):
    pin_text = "📍 Открепить" if pinned else "📌 Закрепить"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=pin_text,
                    callback_data=f"pin_memory:{memory_id}"
                ),
                InlineKeyboardButton(
                    text="🗑 Удалить",
                    callback_data=f"delete_memory:{memory_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏷 Ред. теги",
                    callback_data=f"edit_tags:{memory_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📂 Ред. категорию",
                    callback_data=f"edit_category:{memory_id}"
                )
            ]
        ]
    )

def get_memory_card_keyboard(memory_id: int, pinned: bool = False):
    pin_text = "📍 Открепить" if pinned else "📌 Закрепить"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Удалить",
                    callback_data=f"delete_memory:{memory_id}"
                ),
                InlineKeyboardButton(
                    text="🔎 Похожее",
                    callback_data=f"similar_memory:{memory_id}"
                ),
                InlineKeyboardButton(
                    text=pin_text,
                    callback_data=f"pin_memory:{memory_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Изменить",
                    callback_data=f"edit_memory:{memory_id}"
                ),
                InlineKeyboardButton(
                    text="🏷 Ред. теги",
                    callback_data=f"edit_tags:{memory_id}"
                ),
                InlineKeyboardButton(
                    text="📂 Ред. категорию",
                    callback_data=f"edit_category:{memory_id}"
                )
            ]
        ]
    )

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
    cursor.execute("""
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS category TEXT DEFAULT '📦 Разное'
    """)

    cursor.execute("""
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS content_type TEXT DEFAULT '📝 текст'
    """)

    cursor.execute("""
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS tags TEXT DEFAULT '[]'
    """)

    cursor.execute("""
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS pinned BOOLEAN DEFAULT FALSE
    """)

    cursor.execute("""
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS source_title TEXT
    """)

    cursor.execute("""
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS source_username TEXT
    """)

    cursor.execute("""
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS source_chat_id BIGINT
    """)

    cursor.execute("""
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS source_link TEXT
    """)

    cursor.execute("""
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS media_type TEXT
    """)

    cursor.execute("""
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS media_file_id TEXT
            """)

    cursor.execute("""
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS media_file_ids TEXT DEFAULT '[]'
    """)

    cursor.execute("""
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS formatted_text TEXT
    """)

    conn.commit()
    cursor.close()
    conn.close()


def save_memory(
    user_id: int,
    username: str | None,
    text: str,
    formatted_text: str | None = None
    content_type_override: str | None = None,
    source_title: str | None = None,
    source_username: str | None = None,
    source_chat_id: int | None = None,
    source_link: str | None = None,
    media_type: str | None = None,
    media_file_id: str | None = None,
    media_file_ids: list | None = None
):
    metadata = generate_memory_metadata(text)

    if content_type_override:
        metadata["content_type"] = content_type_override

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO memories (
            user_id, username, text, created_at, category, content_type, tags,
            source_title, source_username, source_chat_id, source_link,
            media_type, media_file_id, media_file_ids, formatted_text
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        user_id,
        username,
        text,
        formatted_text,
        datetime.now(),
        metadata["category"],
        metadata["content_type"],
        json.dumps(metadata["tags"], ensure_ascii=False),
        source_title,
        source_username,
        source_chat_id,
        source_link,
        media_type,
        media_file_id,
        json.dumps(media_file_ids or [], ensure_ascii=False)
    ))

    memory_id = cursor.fetchone()[0]

    conn.commit()
    cursor.close()
    conn.close()

    metadata["memory_id"] = memory_id
    return metadata


def get_recent_memories(user_id: int, limit: int = 5):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, text, created_at, category, content_type, tags
    FROM memories
    WHERE user_id = %s
    ORDER BY id DESC
    LIMIT %s
""", (user_id, limit))

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return rows

def delete_all_memories(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM memories
        WHERE user_id = %s
    """, (user_id,))

    deleted_count = cursor.rowcount

    conn.commit()
    cursor.close()
    conn.close()

    return deleted_count

def get_all_user_tags(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT tags
        FROM memories
        WHERE user_id = %s
    """, (user_id,))

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    tag_counter = {}

    for row in rows:
        tags = row[0]

        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []

        if not isinstance(tags, list):
            continue

        for tag in tags:
            clean_tag = str(tag).lower().strip().replace("#", "")
            if not clean_tag:
                continue

            tag_counter[clean_tag] = tag_counter.get(clean_tag, 0) + 1

    return sorted(
        tag_counter.items(),
        key=lambda item: item[1],
        reverse=True
    )

def get_all_user_categories(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT category, COUNT(*)
        FROM memories
        WHERE user_id = %s
        GROUP BY category
        ORDER BY COUNT(*) DESC
    """, (user_id,))

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return rows

def search_memories(user_id: int, query: str, limit: int = 10):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, text, created_at, category, content_type, tags
        FROM memories
        WHERE user_id = %s
        AND text ILIKE %s
        ORDER BY pinned DESC, id DESC
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

def search_memories_by_tag(user_id: int, tag: str, limit: int = 10):
    clean_tag = (
        tag.lower()
        .replace("#", "")
        .replace(" ", "")
        .replace("-", "")
        .strip()
    )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, text, created_at, category, content_type, tags, pinned
        FROM memories
        WHERE user_id = %s
        AND tags ILIKE %s
        ORDER BY pinned DESC, id DESC
        LIMIT %s
    """, (
        user_id,
        f"%{clean_tag}%",
        limit
    ))

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return rows

def search_memories_by_category(user_id: int, category: str, limit: int = 10):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, text, created_at, category, content_type, tags, pinned
        FROM memories
        WHERE user_id = %s
        AND category = %s
        ORDER BY pinned DESC, id DESC
        LIMIT %s
    """, (
        user_id,
        category,
        limit
    ))

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return rows

def search_memories_by_content_type(user_id: int, content_type: str, limit: int = 10):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, text, created_at, category, content_type, tags, pinned
        FROM memories
        WHERE user_id = %s
        AND content_type = %s
        ORDER BY pinned DESC, id DESC
        LIMIT %s
    """, (
        user_id,
        content_type,
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
        SELECT id, text, created_at, category, content_type, tags, pinned
        FROM memories
        WHERE user_id = %s
        ORDER BY pinned DESC, id DESC
        LIMIT %s
    """, (user_id, limit))

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return rows


def ai_select_memory_ids(query: str, memories: str):
    prompt = f"""
Ты выбираешь релевантные записи из личной памяти пользователя.

Запрос пользователя:
{query}

Записи памяти:
{memories}

Правила:
- выбери только реально релевантные записи;
- ID записи указан после "ID:"; возвращай именно эти ID;
- не придумывай новые факты;
- верни максимум 3 записи;
- ответь ТОЛЬКО JSON-массивом ID.

Пример ответа:
[12, 8, 3]
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": "Ты точный поисковый классификатор. Возвращай только JSON-массив ID."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    content = response.choices[0].message.content.strip()

    try:
        ids = json.loads(content)
    except Exception:
        match = re.search(r"\[[\d,\s]+\]", content)
        if not match:
            return []
        ids = json.loads(match.group(0))

    return [int(item) for item in ids][:3]

def ai_find_similar(source_text: str, memories: str):
    prompt = f"""
Ты ищешь похожие записи в личной памяти пользователя.

Исходная запись:
{source_text}

Другие записи памяти:
{memories}

Задача:
- найти записи, которые похожи по смыслу, теме или контексту;
- не включать исходную запись;
- не придумывать факты;
- если похожих записей нет, так и скажи;
- покажи максимум 3 записи.

Формат ответа:
🔎 Похожие записи

1. Короткий заголовок
🕒 дата и время
Краткое описание в 1 предложении.
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты точный AI-поисковик по личной памяти. "
                    "Ты ищешь только по предоставленным записям и ничего не придумываешь."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    return response.choices[0].message.content

def format_moscow_datetime(created_at):
    months = [
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря"
    ]

    dt = to_moscow_time(created_at)

    return f"{dt.day} {months[dt.month - 1]}, {dt.strftime('%H:%M')} МСК"


def make_memory_preview(text: str, limit: int = 180):
    if len(text) <= limit:
        return text

    return text[:limit].strip() + "..."


def guess_memory_emoji(text: str):
    text_lower = text.lower()

    if any(word in text_lower for word in ["ноутбук", "компьютер", "macbook", "thinkpad", "zenbook"]):
        return "💻"

    if any(word in text_lower for word in ["машина", "авто", "ауди", "bmw", "kia", "hyundai"]):
        return "🚗"

    if any(word in text_lower for word in ["деньги", "расходы", "бюджет", "финансы"]):
        return "💰"

    if any(word in text_lower for word in ["дизайн", "бренд", "логотип", "визуал"]):
        return "🎨"

    if any(word in text_lower for word in ["учёба", "универ", "реферат", "презентация"]):
        return "📚"

    return "📝"


def build_search_response(selected_rows):
    response = f"🧠 Нашёл {len(selected_rows)} записи\n\n"

    for index, row in enumerate(selected_rows, start=1):
        memory_id, text, created_at, category, content_type, tags, pinned = row

        preview = make_memory_preview(text)
        date_text = format_moscow_datetime(created_at)
        tag_text = format_tags(tags)

        pin_icon = "📌 " if pinned else ""

        response += f"{index}. {pin_icon}{category} Запись из памяти\n"
        response += f"🕒 {date_text}\n"
        response += f"{content_type}\n"

        if tag_text:
            response += f"{tag_text}\n"

        response += f"\n{preview}\n\n"

    return response.strip()

def build_single_memory_response(row):
    memory_id, text, created_at, category, content_type, tags = row

    preview = make_memory_preview(text)
    tag_text = format_tags(tags)

    response = (
        f"✅ Запись обновлена\n\n"
        f"{category} Запись из памяти\n"
        f"🕒 {format_moscow_datetime(created_at)}\n"
        f"{content_type}\n"
    )

    if tag_text:
        response += f"{tag_text}\n"

    response += f"\n{preview}"

    return response

def build_search_keyboard(selected_rows):
    keyboard = []

    for index, row in enumerate(selected_rows, start=1):
        memory_id = row[0]
        pinned = row[6]

        pin_text = f"📍 {index} открепить" if pinned else f"📌 {index} закрепить"

        keyboard.append([
            InlineKeyboardButton(
                text=f"📄 {index} полностью",
                callback_data=f"full:{memory_id}"
            ),
            InlineKeyboardButton(
                text=f"🗑 {index} удалить",
                callback_data=f"delete:{memory_id}"
            ),
            InlineKeyboardButton(
                text=pin_text,
                callback_data=f"pin_memory:{memory_id}"
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def build_content_types_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Текст", callback_data="type:📝 текст"),
                InlineKeyboardButton(text="🔗 Ссылки", callback_data="type:🔗 ссылка")
            ],
            [
                InlineKeyboardButton(text="🖼 Фото", callback_data="type:🖼 фото"),
                InlineKeyboardButton(text="🎬 Видео", callback_data="type:🎬 видео")
            ],
            [
                InlineKeyboardButton(text="🎙 Голосовые", callback_data="type:🎙 голосовое"),
                InlineKeyboardButton(text="⭕ Кружки", callback_data="type:⭕ кружок")
            ]
        ]
    )

def build_edit_category_keyboard(memory_id: int):
    categories = [
        "💼 Работа",
        "📚 Учёба",
        "🚗 Авто",
        "💰 Финансы",
        "🎨 Дизайн",
        "💻 Техника",
        "🧠 Идеи",
        "🏠 Быт",
        "🔒 Приватное",
        "🔗 Материалы",
        "📦 Разное"
    ]

    keyboard = []

    for category in categories:
        keyboard.append([
            InlineKeyboardButton(
                text=category,
                callback_data=f"set_category:{memory_id}:{category}"
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def build_categories_keyboard(categories):
    keyboard = []

    for category, count in categories:
        keyboard.append([
            InlineKeyboardButton(
                text=f"{category} — {count}",
                callback_data=f"category:{category}"
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def is_natural_search_query(text: str) -> bool:
    text_lower = text.lower().strip()

    search_triggers = [
        # Прямой поиск
        "найди",
        "поищи",
        "отыщи",
        "покажи",
        "проверь",
        "посмотри",
        "вспомни",
        "напомни",
        "достань",
        "вытащи",

        # Вопросы про сохранённое
        "что я сохранял",
        "что я сохраняла",
        "я сохранял",
        "я сохраняла",
        "сохранял ли я",
        "сохраняла ли я",
        "сохранял что-то",
        "сохраняла что-то",
        "сохранял что-нибудь",
        "сохраняла что-нибудь",
        "что я записывал",
        "что я записывала",
        "я записывал",
        "я записывала",
        "я писал",
        "я писала",
        "писал что-то",
        "писала что-то",
        "писал что-нибудь",
        "писала что-нибудь",

        # Формулировки через память
        "в памяти есть",
        "в памяти было",
        "в моей памяти",
        "у меня в памяти",
        "в сохранениях есть",
        "в сохранениях было",
        "в моих сохранениях",
        "среди сохранений",
        "среди записей",
        "среди заметок",

        # Формулировки через наличие
        "есть ли у меня",
        "есть что-то про",
        "есть что-нибудь про",
        "у меня есть",
        "у меня было",
        "было что-то про",
        "было что-нибудь про",
        "была ли запись про",
        "была заметка про",
        "были ли записи про",
        "были заметки про",

        # Формулировки через тему
        "что было про",
        "что есть про",
        "что-нибудь про",
        "что-то про",
        "про что я писал",
        "про что я сохранял",
        "что я писал про",
        "что я сохранял про",
        "что я записывал про",
                "че было про",
        "чё было про",
        "че есть про",
        "чё есть про",
        "что было по",
        "че было по",
        "чё было по",
        "что есть по",
        "че есть по",
        "чё есть по",
        "что было о",
        "че было о",
        "чё было о",
        "что есть о",
        "че есть о",
        "чё есть о",

        "что сохранено про",
        "че сохранено про",
        "чё сохранено про",
        "что сохранено по",
        "че сохранено по",
        "чё сохранено по",
        "что у меня было про",
        "че у меня было про",
        "чё у меня было про",
        "что у меня есть про",
        "че у меня есть про",
        "чё у меня есть про",
        "что сохранял про",
        "че сохранял про",
        "чё сохранял про",
        "что записывал про",
        "че записывал про",
        "чё записывал про",

        # Разговорные варианты
        "помнишь",
        "помнишь ли",
        "не помнишь",
        "у нас было",
        "у нас есть",
        "мы сохраняли",
        "мы записывали",
        "я кидал",
        "я кидала",
        "я скидывал",
        "я скидывала",
        "я отправлял",
        "я отправляла",

        # Варианты с просьбой
        "можешь найти",
        "можешь поискать",
        "можешь показать",
        "можешь вспомнить",
        "можешь достать",
        "можешь вытащить",
        "можешь проверить",
        "найдешь",
        "найдёшь",
        "поищешь",
        "покажешь",
        "вспомнишь",

        # Более естественные запросы
        "мне нужно найти",
        "мне надо найти",
        "надо найти",
        "нужно найти",
        "хочу найти",
        "хочу посмотреть",
        "хочу вспомнить",
        "помоги найти",
        "помоги вспомнить",
        "помоги достать",

        # Разговорно-грубые варианты
        "найди блин",
        "найди уже",
        "найди нах",
        "найди нахуй",
        "поищи нах",
        "поищи нахуй",
        "где блять",
        "где блядь",
        "где нах",
        "где нахуй",
        "что там было",
        "что там у меня",
        "что за хрень была",
        "что за фигня была",
        "что за штука была",
        "где эта хрень",
        "где эта фигня",
        "где эта штука",
        "вспомни блять",
        "вспомни нахуй",
        "покажи блять",
        "покажи нахуй",

        # Грубые конструкции с "хуйня" — только поисковые формулировки
        "где та хуйня",
        "где эта хуйня",
        "где та самая хуйня",
        "где эта самая хуйня",
        "найди ту хуйню",
        "найди эту хуйню",
        "поищи ту хуйню",
        "поищи эту хуйню",
        "покажи ту хуйню",
        "покажи эту хуйню",
        "вспомни ту хуйню",
        "вспомни эту хуйню",
        "что за хуйня была",
        "чё за хуйня была",
        "че за хуйня была",
        "что за хуйня",
        "чё за хуйня",
        "че за хуйня",
        "какая хуйня была",
        "какую хуйню я сохранял",
        "какую хуйню я сохраняла",
        "какую хуйню я писал",
        "какую хуйню я писала",
        "та хуйня где",
        "эта хуйня где",
        "та самая хуйня где",
        "эта самая хуйня где",
        "была хуйня про",
        "была какая-то хуйня про",
        "была какая то хуйня про",
        "есть хуйня про",
        "есть какая-то хуйня про",
        "есть какая то хуйня про",
    ]

    return any(trigger in text_lower for trigger in search_triggers)


def clean_search_query(text: str) -> str:
    query = text.lower().strip()

    phrases_to_remove = [
        # Прямой поиск
        "найди",
        "поищи",
        "отыщи",
        "покажи",
        "проверь",
        "посмотри",
        "вспомни",
        "напомни",
        "достань",
        "вытащи",

        # Вопросы про сохранённое
        "что я сохранял",
        "что я сохраняла",
        "я сохранял",
        "я сохраняла",
        "сохранял ли я",
        "сохраняла ли я",
        "сохранял что-то",
        "сохраняла что-то",
        "сохранял что-нибудь",
        "сохраняла что-нибудь",
        "что я записывал",
        "что я записывала",
        "я записывал",
        "я записывала",
        "я писал",
        "я писала",
        "писал что-то",
        "писала что-то",
        "писал что-нибудь",
        "писала что-нибудь",

        # Формулировки через память
        "в памяти есть",
        "в памяти было",
        "в моей памяти",
        "у меня в памяти",
        "в сохранениях есть",
        "в сохранениях было",
        "в моих сохранениях",
        "среди сохранений",
        "среди записей",
        "среди заметок",

        # Формулировки через наличие
        "есть ли у меня",
        "есть что-то про",
        "есть что-нибудь про",
        "у меня есть",
        "у меня было",
        "было что-то про",
        "было что-нибудь про",
        "была ли запись про",
        "была заметка про",
        "были ли записи про",
        "были заметки про",

        # Формулировки через тему
        "что было про",
        "что есть про",
        "что-нибудь про",
        "что-то про",
        "про что я писал",
        "про что я сохранял",
        "что я писал про",
        "что я сохранял про",
        "что я записывал про",
                "че было про",
        "чё было про",
        "че есть про",
        "чё есть про",
        "что было по",
        "че было по",
        "чё было по",
        "что есть по",
        "че есть по",
        "чё есть по",
        "что было о",
        "че было о",
        "чё было о",
        "что есть о",
        "че есть о",
        "чё есть о",

        "что сохранено про",
        "че сохранено про",
        "чё сохранено про",
        "что сохранено по",
        "че сохранено по",
        "чё сохранено по",
        "что у меня было про",
        "че у меня было про",
        "чё у меня было про",
        "что у меня есть про",
        "че у меня есть про",
        "чё у меня есть про",
        "что сохранял про",
        "че сохранял про",
        "чё сохранял про",
        "что записывал про",
        "че записывал про",
        "чё записывал про",

        # Разговорные варианты
        "помнишь",
        "помнишь ли",
        "не помнишь",
        "у нас было",
        "у нас есть",
        "мы сохраняли",
        "мы записывали",
        "я кидал",
        "я кидала",
        "я скидывал",
        "я скидывала",
        "я отправлял",
        "я отправляла",

        # Варианты с просьбой
        "можешь найти",
        "можешь поискать",
        "можешь показать",
        "можешь вспомнить",
        "можешь достать",
        "можешь вытащить",
        "можешь проверить",
        "найдешь",
        "найдёшь",
        "поищешь",
        "покажешь",
        "вспомнишь",

        # Более естественные запросы
        "мне нужно найти",
        "мне надо найти",
        "надо найти",
        "нужно найти",
        "хочу найти",
        "хочу посмотреть",
        "хочу вспомнить",
        "помоги найти",
        "помоги вспомнить",
        "помоги достать",

        # Разговорно-грубые варианты
        "найди блин",
        "найди уже",
        "найди нах",
        "найди нахуй",
        "поищи нах",
        "поищи нахуй",
        "где блять",
        "где блядь",
        "где нах",
        "где нахуй",
        "что там было",
        "что там у меня",
        "что за хрень была",
        "что за фигня была",
        "что за штука была",
        "где эта хрень",
        "где эта фигня",
        "где эта штука",
        "вспомни блять",
        "вспомни нахуй",
        "покажи блять",
        "покажи нахуй",

        # Грубые конструкции с "хуйня" — только поисковые формулировки
        "где та самая хуйня",
        "где эта самая хуйня",
        "где та хуйня",
        "где эта хуйня",
        "найди ту хуйню",
        "найди эту хуйню",
        "поищи ту хуйню",
        "поищи эту хуйню",
        "покажи ту хуйню",
        "покажи эту хуйню",
        "вспомни ту хуйню",
        "вспомни эту хуйню",
        "что за хуйня была",
        "чё за хуйня была",
        "че за хуйня была",
        "что за хуйня",
        "чё за хуйня",
        "че за хуйня",
        "какая хуйня была",
        "какую хуйню я сохранял",
        "какую хуйню я сохраняла",
        "какую хуйню я писал",
        "какую хуйню я писала",
        "та самая хуйня где",
        "эта самая хуйня где",
        "та хуйня где",
        "эта хуйня где",
        "была какая-то хуйня про",
        "была какая то хуйня про",
        "была хуйня про",
        "есть какая-то хуйня про",
        "есть какая то хуйня про",
        "есть хуйня про",

        # Мусорные слова
        "пожалуйста",
        "плиз",
        "плз",
        "короче",
        "типа",
        "ну",
        "в общем",
        "там",
        "мне",
        "моя",
        "мой",
        "моё"
    ]

    phrases_to_remove = sorted(phrases_to_remove, key=len, reverse=True)

    for phrase in phrases_to_remove:
        query = query.replace(phrase, "")

    query = query.strip(" .,!?:;—-")

    if not query:
        return text

    return query

def format_memory_list(memories, title: str):
    response = f"{title}\n\n"

    for index, row in enumerate(memories, start=1):
        memory_id, text, created_at, category, content_type, tags = row

        short_text = text[:300]

        if len(text) > 300:
            short_text += "..."

        moscow_time = to_moscow_time(created_at)
        tag_text = format_tags(tags)

        response += f"{index}. {category} {short_text}\n"
        response += f"   🕒 {moscow_time.strftime('%Y-%m-%d %H:%M:%S')} МСК\n"
        response += f"   {content_type}\n"

        if tag_text:
            response += f"   {tag_text}\n"

        response += "\n"

    return response


@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer(
    "👋 Привет. Это Memorix.\n\n"
    "Твоя личная AI-память.\n\n"
    "Сохраняй мысли, идеи, голосовые сообщения, ссылки и важные детали.\n"
    "Memorix запомнит их и поможет найти в нужный момент.\n\n"
    "Просто отправь сообщение 👇",
    reply_markup=main_keyboard
)


@dp.message(Command("help"))
async def help_handler(message: Message):
    await message.answer(
        "🧠 Memorix — персональная AI-память в Telegram.\n\n"
        "Сохраняй текст, голосовые, ссылки, идеи и заметки. "
        "Memorix сам определит категорию, тип записи и теги.\n\n"
        "Как искать:\n"
        "• /search запрос\n"
        "• кнопка 🔍 Поиск\n"
        "• или просто напиши: «найди заметку про бренд»\n\n"
        "Категории:\n"
        "💼 Работа — задачи, встречи, проекты\n"
        "📚 Учёба — лекции, задания, источники\n"
        "🚗 Авто — машины, расходы, обслуживание\n"
        "💰 Финансы — деньги, бюджет, покупки\n"
        "🎨 Дизайн — визуал, бренд, оформление\n"
        "💻 Техника — устройства, сервисы, приложения\n"
        "🧠 Идеи — мысли, планы, концепции\n"
        "🏠 Быт — дом, дела, повседневное\n"
        "🔒 Приватное — личные заметки и планы\n"
        "🔗 Материалы — ссылки, статьи, документы\n"
        "📦 Разное — всё, что не подошло выше\n\n"
        "Команды:\n"
        "/memory — последние записи\n"
        "/pinned — закреплённые записи\n"
        "/today — сохранения за сегодня\n"
        "/search запрос — AI-поиск\n"
        "/reset — удалить всю память\n"
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
        SELECT id, text, created_at, category, content_type, tags
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

@dp.message(Command("pinned"))
async def pinned_memories_handler(message: Message):
    rows = get_pinned_memories(
        message.from_user.id
    )

    if not rows:
        await message.answer(
            "📌 Закреплённых записей пока нет."
        )
        return

    await message.answer(
        build_search_response(rows),
        reply_markup=build_search_keyboard(rows)
    )

@dp.message(Command("reset"))
async def reset_handler(message: Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, удалить память",
                    callback_data="confirm_reset"
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data="cancel_reset"
                )
            ]
        ]
    )

    await message.answer(
        "⚠️ Сброс памяти\n\n"
        "Это действие полностью удалит все твои сохранённые записи в Memorix.\n\n"
        "Восстановить их после удаления будет нельзя.\n\n"
        "Точно удалить всю память?",
        reply_markup=keyboard
    )


@dp.callback_query(lambda callback: callback.data == "confirm_reset")
async def confirm_reset_handler(callback: CallbackQuery):
    deleted_count = delete_all_memories(callback.from_user.id)

    await callback.message.edit_text(
        f"🗑 Память очищена.\n\n"
        f"Удалено записей: {deleted_count}"
    )

    await callback.answer()


@dp.callback_query(lambda callback: callback.data == "cancel_reset")
async def cancel_reset_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "Отмена. Память осталась без изменений."
    )

    await callback.answer()

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
        await message.answer("😶 Память пока пустая.")
        return

    memories = "\n".join([
        f"{'📌 ' if row[6] else ''}ID:{row[0]} [{to_moscow_time(row[2]).strftime('%Y-%m-%d %H:%M:%S')} МСК] {row[1]}"
        for row in rows
    ])

    selected_ids = ai_select_memory_ids(query, memories)

    row_map = {
        row[0]: row
        for row in rows
    }

    selected_rows = [
        row_map[memory_id]
        for memory_id in selected_ids
        if memory_id in row_map
    ]

    if not selected_rows:
        await message.answer("Ничего релевантного не нашёл.")
        return

    await message.answer(build_search_response(selected_rows))

    for row in selected_rows:
        await message.answer(
            f"Действия для записи {row[0]}",
            reply_markup=get_memory_card_keyboard(
                row[0],
                row[6]  # pinned
            )
        )

@dp.message(lambda message: message.text and is_natural_search_query(message.text))
async def natural_search_handler(message: Message):
    query = clean_search_query(message.text)

    rows = get_last_memories_for_ai(message.from_user.id)

    if not rows:
        await message.answer("😶 Память пока пустая.")
        return

    memories = "\n".join([
        f"{'📌 ' if row[6] else ''}ID:{row[0]} [{to_moscow_time(row[2]).strftime('%Y-%m-%d %H:%M:%S')} МСК] {row[1]}"
        for row in rows
    ])

    selected_ids = ai_select_memory_ids(query, memories)

    row_map = {
        row[0]: row
        for row in rows
    }

    selected_rows = [
        row_map[memory_id]
        for memory_id in selected_ids
        if memory_id in row_map
    ]

    if not selected_rows:
        await message.answer("Ничего релевантного не нашёл.")
        return

    await message.answer(
        build_search_response(selected_rows),
        reply_markup=build_search_keyboard(selected_rows)
    )


@dp.message(lambda message: message.voice)
async def voice_handler(message: Message):
    status_message = await message.answer("🎙 Обрабатываю голосовое...")

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

        if is_natural_search_query(text):
            query = clean_search_query(text)

            rows = get_last_memories_for_ai(message.from_user.id)

            if not rows:
                await status_message.edit_text("😶 Память пока пустая.")
                return

            memories = "\n".join([
                f"ID: {row[0]} | DATE: {to_moscow_time(row[2]).strftime('%Y-%m-%d %H:%M:%S')} МСК | CATEGORY: {row[3]} | TYPE: {row[4]} | TAGS: {format_tags(row[5])} | TEXT: {row[1]}"
                for row in rows
            ])

            selected_ids = ai_select_memory_ids(query, memories)

            row_map = {
                row[0]: row
                for row in rows
            }

            selected_rows = [
                row_map[memory_id]
                for memory_id in selected_ids
                if memory_id in row_map
            ]

            if not selected_rows:
                await status_message.edit_text("Ничего релевантного не нашёл.")
                return

            await status_message.edit_text(
                f"🎙 Распознал запрос: «{text}»"
            )

            await message.answer(
                build_search_response(selected_rows),
                reply_markup=build_search_keyboard(selected_rows)
            )

            return

        metadata = save_memory(
            user_id=message.from_user.id,
            username=message.from_user.username,
            text=text
        )
        formatted_tags = format_tags(
            metadata.get("tags", [])
        )

        voice_preview = make_preview(text)

        if formatted_tags:
            await status_message.edit_text(
                "🎙 Голосовое сохранено\n\n"
                f"📝 {voice_preview}\n"
                f"🏷 {formatted_tags}",
                reply_markup=get_memory_card_keyboard(
                                metadata["memory_id"],
                                False
                            )
            )
        else:
            await status_message.edit_text(
                "🎙 Голосовое сохранено\n\n"
                f"📝 {voice_preview}"
            )

    except Exception as error:
        print(f"Voice processing error: {error}")
        await status_message.edit_text(
            "Не получилось обработать голосовое. Попробуй ещё раз."
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

@dp.message(lambda message: message.text == "📌 Закреплённые")
async def pinned_button_handler(message: Message):
    await pinned_memories_handler(message)

@dp.message(lambda message: message.text == "🔍 Поиск")
async def search_button_handler(message: Message):
    await message.answer(
        "Напиши:\n/search твой запрос"
    )

@dp.message(lambda message: message.text == "🧩 Типы контента")
async def content_types_button_handler(message: Message):
    await message.answer(
        "🧩 Выбери тип записей:",
        reply_markup=build_content_types_keyboard()
    )

@dp.message(lambda message: message.text == "🏷 Теги")
async def tags_button_handler(message: Message):
    tags = get_all_user_tags(message.from_user.id)

    if not tags:
        await message.answer(
            "🏷 Тегов пока нет."
        )
        return

    response = "🏷 Все теги\n\n"

    for tag, count in tags[:30]:
        response += f"#{tag} — {count}\n"

    response += "\nНажми на тег или отправь его сообщением, например: #работа"

    await message.answer(response)

@dp.message(lambda message: message.text == "📂 Категории")
async def categories_button_handler(message: Message):
    categories = get_all_user_categories(message.from_user.id)

    if not categories:
        await message.answer("📂 Категорий пока нет.")
        return

    await message.answer(
        "📂 Категории памяти\n\n"
        "Выбери категорию:",
        reply_markup=build_categories_keyboard(categories)
    )

def get_memory_by_id(user_id: int, memory_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            id, text, created_at, category, content_type, tags,
            source_title, source_link,
            media_type, media_file_id, media_file_ids,
            pinned,
            formatted_text
        FROM memories
        WHERE user_id = %s AND id = %s
    """, (user_id, memory_id))

    row = cursor.fetchone()

    cursor.close()
    conn.close()

    return row

def get_memory_tags_by_id(user_id: int, memory_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT tags
        FROM memories
        WHERE user_id = %s AND id = %s
    """, (user_id, memory_id))

    row = cursor.fetchone()

    cursor.close()
    conn.close()

    if not row:
        return []

    tags = row[0]

    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = []

    if not isinstance(tags, list):
        tags = []

    return tags

def delete_memory_by_id(user_id: int, memory_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM memories
        WHERE user_id = %s AND id = %s
    """, (user_id, memory_id))

    deleted_count = cursor.rowcount

    conn.commit()
    cursor.close()
    conn.close()

    return deleted_count > 0

def update_memory_text(
    user_id: int,
    memory_id: int,
    new_text: str,
    formatted_text: str | None = None
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE memories
        SET text = %s
        WHERE user_id = %s
        AND id = %s
        """,
        (
            new_text,
            formatted_text,
            user_id,
            memory_id
        )
    )

    conn.commit()

    cursor.close()
    conn.close()

def update_memory_category(user_id: int, memory_id: int, category: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE memories
        SET category = %s
        WHERE user_id = %s AND id = %s
    """, (
        category,
        user_id,
        memory_id
    ))

    conn.commit()
    cursor.close()
    conn.close()

def update_memory_tags(user_id: int, memory_id: int, tags: list[str]):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE memories
        SET tags = %s
        WHERE user_id = %s AND id = %s
    """, (
        json.dumps(tags, ensure_ascii=False),
        user_id,
        memory_id
    ))

    conn.commit()
    cursor.close()
    conn.close()

def toggle_pin_memory(user_id: int, memory_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE memories
        SET pinned = NOT pinned
        WHERE user_id = %s AND id = %s
        RETURNING pinned
    """, (user_id, memory_id))

    result = cursor.fetchone()

    conn.commit()
    cursor.close()
    conn.close()

    if result:
        return result[0]

    return None    

def get_pinned_memories(user_id: int, limit: int = 10):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, text, created_at, category, content_type, tags, pinned
        FROM memories
        WHERE user_id = %s AND pinned = TRUE
        ORDER BY id DESC
        LIMIT %s
    """, (user_id, limit))

    rows = cursor.fetchall()

    cursor.close()
    conn.close()

    return rows


@dp.callback_query(lambda callback: callback.data.startswith("full:"))
async def full_memory_handler(callback: CallbackQuery):
    memory_id = int(callback.data.split(":")[1])

    row = get_memory_by_id(
        callback.from_user.id,
        memory_id
    )

    if not row:
        await callback.answer("Запись не найдена.")
        return

    (
        memory_id,
        text,
        created_at,
        category,
        content_type,
        tags,
        source_title,
        source_link,
        media_type,
        media_file_id,
        media_file_ids,
        pinned,
        formatted_text
    ) = row

    display_text = formatted_text or html.escape(text)

    source_line = ""

    if source_title:
        source_line = f"📣 {source_title}\n"

    if source_link:
        source_line += f"🔗 {source_link}\n"

    tag_text = format_tags(tags)

    response = (
        f"📄 Полная запись\n\n"
        f"{source_line}"
        f"{category}\n"
        f"{content_type}\n"
        f"🏷 {tag_text}\n"
        f"🕒 {format_moscow_datetime(created_at)}\n\n"
        f"{display_text}"
    )

    parse_mode="HTML"

    
    file_ids = []

    if media_file_ids:
        try:
            file_ids = json.loads(media_file_ids)
        except Exception:
            file_ids = []

    if not file_ids and media_file_id:
        file_ids = [media_file_id]

    if file_ids and media_type in ["photo", "album"]:
        if len(file_ids) == 1 and len(response) <= 1024:
            await callback.message.answer_photo(
                photo=file_ids[0],
                caption=response,
                parse_mode="HTML"
            )
        else:
            await callback.message.answer(
                response,
                parse_mode="HTML"
            )

            for file_id in file_ids:
                await callback.message.answer_photo(file_id)

    elif file_ids and media_type == "video":
        if len(response) <= 1024:
            await callback.message.answer_video(
                video=file_ids[0],
                caption=response,
                parse_mode="HTML"
            )
        else:
            await callback.message.answer(
                response,
                parse_mode="HTML"
            )
            await callback.message.answer_video(file_ids[0])

    elif file_ids and media_type == "video_note":
        await callback.message.answer(
            response,
            parse_mode="HTML"
        )
        await callback.message.answer_video_note(file_ids[0])

    else:
        await callback.message.answer(
            response,
            parse_mode="HTML"
        )

    await callback.answer()

@dp.callback_query(lambda callback: callback.data.startswith("type:"))
async def content_type_callback(callback: CallbackQuery):
    content_type = callback.data.replace("type:", "", 1)

    rows = search_memories_by_content_type(
        callback.from_user.id,
        content_type
    )

    if not rows:
        await callback.answer(
            "Записей этого типа пока нет.",
            show_alert=True
        )
        return

    await callback.message.answer(
        build_search_response(rows),
        reply_markup=build_search_keyboard(rows)
    )

    await callback.answer()

@dp.callback_query(lambda callback: callback.data.startswith("delete:"))
async def delete_search_callback(callback: CallbackQuery):
    memory_id = int(callback.data.split(":")[1])

    deleted = delete_memory_by_id(callback.from_user.id, memory_id)

    if not deleted:
        await callback.answer("Запись не найдена.", show_alert=True)
        return

    await callback.answer("Удалено.")
    await callback.message.answer("🗑 Запись удалена из памяти.")

@dp.callback_query(lambda c: c.data.startswith("delete_memory:"))
async def delete_memory_card_callback(callback: CallbackQuery):
    memory_id = int(
        callback.data.split(":")[1]
    )

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM memories WHERE id = %s",
        (memory_id,)
    )

    conn.commit()

    cursor.close()
    conn.close()

    await callback.message.edit_text(
        "🗑 Запись удалена"
    )

    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("similar_memory:"))
async def similar_memory_card_callback(callback: CallbackQuery):
    memory_id = int(
        callback.data.split(":")[1]
    )

    source = get_memory_by_id(
        callback.from_user.id,
        memory_id
    )

    if not source:
        await callback.answer(
            "Запись не найдена.",
            show_alert=True
        )
        return

    source_text = source[1]

    rows = get_last_memories_for_ai(
        callback.from_user.id
    )

    if not rows:
        await callback.answer(
            "Похожих записей пока нет.",
            show_alert=True
        )
        return

    memories = "\n".join([
        f"[{to_moscow_time(row[2]).strftime('%Y-%m-%d %H:%M:%S')} МСК] {row[1]}"
        for row in rows
        if row[1] != source_text
  ])

    if not memories.strip():
        await callback.answer(
            "Похожих записей пока нет.",
            show_alert=True
        )
        return

    result = ai_find_similar(
        source_text,
        memories
    )

    await callback.message.answer(result)

    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("pin_memory:"))
async def pin_memory_callback(callback: CallbackQuery):
    memory_id = int(callback.data.split(":")[1])

    pinned = toggle_pin_memory(
        callback.from_user.id,
        memory_id
    )

    if pinned is None:
        await callback.answer(
            "Запись не найдена.",
            show_alert=True
        )
        return

    if pinned:
        text = "📌 Запись закреплена"
    else:
        text = "📍 Запись откреплена"

    await callback.message.edit_reply_markup(
        reply_markup=get_memory_card_keyboard(
            memory_id,
            pinned
        )
    )

    await callback.answer(text)   

@dp.callback_query(lambda c: c.data.startswith("edit_memory:"))
async def edit_memory_callback(
    callback: CallbackQuery,
    state: FSMContext
):
    memory_id = int(callback.data.split(":")[1])

    row = get_memory_by_id(
        callback.from_user.id,
        memory_id
    )

    if not row:
        await callback.answer("Запись не найдена.", show_alert=True)
        return

    old_text = row[1]

    await state.update_data(
        memory_id=memory_id,
        old_text=old_text
    )

    await state.set_state(
        EditMemoryState.waiting_for_text
    )

    safe_old_text = html.escape(old_text)

    await callback.message.answer(
        "✏️ Текущий текст / подпись:\n\n"
        f"<pre>{safe_old_text}</pre>\n\n"
        "Отправь новый текст.\n"
        "Он заменит текст записи или станет подписью к медиа.",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("edit_tags:"))
async def edit_tags_callback(
    callback: CallbackQuery,
    state: FSMContext
):
    memory_id = int(callback.data.split(":")[1])

    current_tags = get_memory_tags_by_id(
        callback.from_user.id,
        memory_id
    )

    current_tags_text = format_tags(current_tags)

    if not current_tags_text:
        current_tags_text = "тегов пока нет"

    await state.update_data(memory_id=memory_id)

    await state.set_state(EditTagsState.waiting_for_tags)

    await callback.message.answer(
        "🏷 Текущие теги:\n\n"
        f"{current_tags_text}\n\n"
        "Отправь новые теги через пробел.\n\n"
        "Например:\n"
        "работа обучение идеи\n\n"
        "Старые теги будут заменены."
    )

    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("edit_category:"))
async def edit_category_callback(callback: CallbackQuery):
    memory_id = int(callback.data.split(":")[1])

    await callback.message.answer(
        "📂 Выбери новую категорию:",
        reply_markup=build_edit_category_keyboard(memory_id)
    )

    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("set_category:"))
async def set_category_callback(callback: CallbackQuery):
    parts = callback.data.split(":", 2)

    memory_id = int(parts[1])
    category = parts[2]

    update_memory_category(
        callback.from_user.id,
        memory_id,
        category
    )

    row = get_memory_by_id(
        callback.from_user.id,
        memory_id
    )

    if not row:
        await callback.answer("Запись не найдена.", show_alert=True)
        return

    (
        memory_id,
        text,
        created_at,
        category,
        content_type,
        tags,
        source_title,
        source_link,
        media_type,
        media_file_id,
        media_file_ids,
        pinned
    ) = row

    await callback.message.answer(
        "Категория обновлена 🔄\n\n"
        f"{category}\n"
        f"{content_type}\n"
        f"🏷 {format_tags(tags)}\n\n"
        f"{make_memory_preview(text)}",
        reply_markup=get_after_edit_keyboard(
            memory_id,
            pinned
        )
    )

    await callback.answer("Категория обновлена")

@dp.callback_query(lambda callback: callback.data.startswith("category:"))
async def category_callback(callback: CallbackQuery):
    category = callback.data.replace("category:", "", 1)

    rows = search_memories_by_category(
        callback.from_user.id,
        category
    )

    if not rows:
        await callback.answer(
            "В этой категории пока нет записей.",
            show_alert=True
        )
        return

    await callback.message.answer(
        build_search_response(rows),
        reply_markup=build_search_keyboard(rows)
    )

    await callback.answer()

@dp.message(EditTagsState.waiting_for_tags)
async def process_edit_tags(
    message: Message,
    state: FSMContext
):

    if not message.text:
        await message.answer(
            "🏷 Отправь теги текстом через пробел."
        )
        return

    raw_tags = message.text.strip().split()

    tags = []

    for tag in raw_tags:
        clean_tag = (
            tag.lower()
            .replace("#", "")
            .replace(" ", "")
            .replace("-", "")
            .strip()
        )

        if clean_tag and clean_tag not in tags:
            tags.append(clean_tag)

    tags = tags[:5]

    if not tags:
        await message.answer(
            "Не вижу тегов. Отправь, например:\nработа идеи проект"
        )
        return

    update_memory_tags(
        message.from_user.id,
        memory_id,
        tags
    )

    await state.clear()

    row = get_memory_by_id(
        message.from_user.id,
        memory_id
    )

    (
        memory_id,
        text,
        created_at,
        category,
        content_type,
        tags,
        source_title,
        source_link,
        media_type,
        media_file_id,
        media_file_ids,
        pinned
    ) = row

    await message.answer(
        "Теги обновлены 🔄\n\n"
        f"{category}\n"
        f"{content_type}\n"
        f"🏷 {format_tags(tags)}\n\n"
        f"{make_memory_preview(text)}",
        reply_markup=get_after_edit_keyboard(
            memory_id,
            pinned
        )
    )

@dp.message(EditMemoryState.waiting_for_text)
async def process_edit_memory(
    message: Message,
    state: FSMContext
):
    data = await state.get_data()

    memory_id = data["memory_id"]
    old_text = data.get("old_text", "")

    update_memory_text(
        message.from_user.id,
        memory_id,
        message.text,
        message.html_text
    )

    row = get_memory_by_id(
        message.from_user.id,
        memory_id
    )

    if not row:
        await message.answer("Запись не найдена.")
        await state.clear()
        return

    (
        memory_id,
        text,
        created_at,
        category,
        content_type,
        tags,
        source_title,
        source_link,
        media_type,
        media_file_id,
        media_file_ids,
        pinned
    ) = row

    safe_old_text = html.escape(old_text)
    safe_new_text = html.escape(text)

    response = (
        "Обновлено 🔄\n\n"
        f"{category}\n"
        f"{content_type}\n"
        f"🏷 {format_tags(tags)}\n\n"
        "━━━━━━━━━━━━━━\n"
        "СТАРАЯ ВЕРСИЯ\n"
        "━━━━━━━━━━━━━━\n"
        f"<pre>{safe_old_text}</pre>\n\n"
        "━━━━━━━━━━━━━━\n"
        "НОВАЯ ВЕРСИЯ\n"
        "━━━━━━━━━━━━━━\n"
        f"<pre>{safe_new_text}</pre>"
    )

    await message.answer(
        response,
        reply_markup=get_after_edit_keyboard(
            memory_id,
            pinned
        ),
        parse_mode="HTML"
    )

    await state.clear()

async def save_media_group_later(group_id: str):
    await asyncio.sleep(2)

    group = media_group_buffer.pop(group_id, None)

    if not group:
        return

    message = group["message"]
    source = group["source"]
    media_items = group["media_items"]

    text = group.get("caption") or "Медиа без подписи"

    first_media = media_items[0]

    metadata = save_memory(
        user_id=message.from_user.id,
        username=message.from_user.username,
        text=text,
        content_type_override="🖼 фото" if first_media["type"] == "photo" else "🎬 видео",
        source_title=source["source_title"],
        source_username=source["source_username"],
        source_chat_id=source["source_chat_id"],
        source_link=source["source_link"],
        media_type="album",
        media_file_id=first_media["file_id"],
        media_file_ids=[
            item["file_id"]
            for item in media_items
        ]
    )

    formatted_tags = format_tags(metadata.get("tags", []))
    preview = make_preview(text)

    source_line = ""
    if source["source_title"]:
        source_line = f"📣 {source['source_title']}\n"

    await message.answer(
        f"🖼 Медиа-пост сохранён\n\n"
        f"{source_line}"
        f"📝 {preview}\n"
        f"🏷 {formatted_tags}",
        reply_markup=get_memory_card_keyboard(
            metadata["memory_id"],
            False
        )
    )

async def transcribe_video_note(message: Message):
    temp_path = None

    try:
        file = await bot.get_file(message.video_note.file_id)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
            temp_path = temp_file.name

        await bot.download_file(file.file_path, temp_path)

        with open(temp_path, "rb") as video_file:
            transcription = client.audio.transcriptions.create(
                model="whisper-1",
                file=video_file,
                language="ru"
            )

        return transcription.text.strip()

    except Exception as error:
        print(f"Video note transcription error: {error}")
        return ""

    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

@dp.message(lambda message: message.photo or message.video or message.video_note)
async def media_handler(message: Message):
    source = extract_forward_source(message)

    if message.photo:
        current_media = {
            "type": "photo",
            "file_id": message.photo[-1].file_id
        }
    elif message.video:
        current_media = {
            "type": "video",
            "file_id": message.video.file_id
        }
    else:
        current_media = {
            "type": "video_note",
            "file_id": message.video_note.file_id
        }

    if message.media_group_id:
        group_id = str(message.media_group_id)

        if group_id not in media_group_buffer:
            media_group_buffer[group_id] = {
                "message": message,
                "source": source,
                "caption": message.caption,
                "media_items": []
            }

            asyncio.create_task(
                save_media_group_later(group_id)
            )

        if message.caption:
            media_group_buffer[group_id]["caption"] = message.caption

        media_group_buffer[group_id]["media_items"].append(current_media)

        return

    if message.photo:
        media_type = "photo"
        media_file_id = message.photo[-1].file_id
        content_type = "🖼 фото"
        title = "🖼 Фото сохранено"
        fallback_text = "Фото без подписи"

    elif message.video:
        media_type = "video"
        media_file_id = message.video.file_id
        content_type = "🎬 видео"
        title = "🎬 Видео сохранено"
        fallback_text = "Видео без подписи"

    else:
        media_type = "video_note"
        media_file_id = message.video_note.file_id
        content_type = "⭕ кружок"
        title = "⭕ Кружок сохранён"
        fallback_text = "Кружок без расшифровки"

    if message.video_note:
        transcribed_text = await transcribe_video_note(message)
        text = transcribed_text or fallback_text
    else:
        text = message.caption or fallback_text

    metadata = save_memory(
        user_id=message.from_user.id,
        username=message.from_user.username,
        text=text,
        formatted_text=message.html_caption if message.caption else None,
        content_type_override=content_type,
        source_title=source["source_title"],
        source_username=source["source_username"],
        source_chat_id=source["source_chat_id"],
        source_link=source["source_link"],
        media_type=media_type,
        media_file_id=media_file_id
    )

    formatted_tags = format_tags(
        metadata.get("tags", [])
    )

    preview = make_preview(text)

    source_line = ""

    if source["source_title"]:
        source_line = f"📣 {source['source_title']}\n"

    await message.answer(
        f"{title}\n\n"
        f"{source_line}"
        f"📝 {preview}\n"
        f"🏷 {formatted_tags}",
        reply_markup=get_memory_card_keyboard(
            metadata["memory_id"],
            False
        )
    )

@dp.message(lambda message: message.text and message.text.strip().startswith("#"))
async def tag_search_handler(message: Message):
    tag = message.text.strip().split()[0]

    rows = search_memories_by_tag(
        message.from_user.id,
        tag
    )

    if not rows:
        await message.answer(
            f"По тегу {tag} ничего не найдено."
        )
        return

    await message.answer(
        build_search_response(rows),
        reply_markup=build_search_keyboard(rows)
    )

@dp.message()
async def save_text_handler(message: Message):
    if not message.text:
        await message.answer(
            "Пока поддерживаются только текст и голосовые сообщения."
        )
        return

    source = extract_forward_source(message)

    metadata = save_memory(
        user_id=message.from_user.id,
        username=message.from_user.username,
        text=message.text,
        formatted_text=message.html_text,
        source_title=source["source_title"],
        source_username=source["source_username"],
        source_chat_id=source["source_chat_id"],
        source_link=source["source_link"]
    )

    content_type = metadata.get("content_type", "text")
    tags = metadata.get("tags", [])

    save_title = get_save_title(content_type)
    formatted_tags = format_tags(tags)

    preview = make_preview(message.text)
    domain = extract_domain(message.text)

    if domain:
        preview_line = f"🌐 {domain}"
    else:
        preview_line = f"📝 {preview}"

    source_line = ""

    if source["source_title"]:
        source_line = f"📣 {source['source_title']}\n"

    if formatted_tags:
        await message.answer(
            f"{save_title}\n\n"
            f"{source_line}"
            f"{preview_line}\n"
            f"🏷 {formatted_tags}",
            reply_markup=get_memory_card_keyboard(
                metadata["memory_id"],
                False 
            )   
        )
    else:
            await message.answer(
                f"{save_title}\n\n"
                f"{source_line}"
                f"{preview_line}\n",
                reply_markup=get_memory_card_keyboard(
                    metadata["memory_id"],
                    False
                )
            )



async def main():
    init_db()
    await bot.set_my_commands([
    BotCommand(command="memory", description="Последние сохранения"),
    BotCommand(command="search", description="AI-поиск по памяти"),
    BotCommand(command="today", description="Сохранения за сегодня"),
    BotCommand(command="reset", description="Сбросить память"),
    BotCommand(command="help", description="Помощь"), 
    BotCommand(command="pinned", description="Закреплённые записи"),
])
    print("Memorix started | VERSION: SEARCH_UI_FIX_002")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())