import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# Получаем токен
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Создаём бота и диспетчер
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# Команда /start
@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer(
        "👋 Привет! Я Remindly — твоя вторая память для Telegram."
    )


# Ответ на любой текст
@dp.message()
async def echo_handler(message: Message):
    await message.answer(
        f"Ты написал:\n{message.text}"
    )


# Запуск бота
async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())