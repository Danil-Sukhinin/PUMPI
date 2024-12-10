import asyncio
import aiosqlite
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from datetime import datetime

# Замените на ваш фактический токен бота. Хардкодинг небезопасен; используйте переменные окружения в продуктиве.
BOT_TOKEN = "8003843825:AAH4vkd9phOfX2TnEK_xIDXrrFu7ssKAUtQ"

# Конфигурация логирования
logging.basicConfig(level=logging.INFO)

# Имя базы данных
DB_NAME = "bot_database.db"

async def setup_database():
    """Создает таблицы в базе данных, если они не существуют."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, 
            username TEXT, 
            preferences TEXT, 
            location_lat REAL, 
            location_lon REAL
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS points_of_interest (
            poi_id INTEGER PRIMARY KEY, 
            name TEXT, 
            address TEXT, 
            latitude REAL, 
            longitude REAL, 
            description TEXT, 
            category TEXT, 
            ratings REAL, 
            reviews_count INTEGER
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS events (
            event_id INTEGER PRIMARY KEY, 
            name TEXT, 
            description TEXT, 
            date_time TEXT, 
            location_id INTEGER, 
            FOREIGN KEY (location_id) REFERENCES points_of_interest (poi_id)
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
            sub_id INTEGER PRIMARY KEY AUTOINCREMENT, 
            user_id INTEGER, 
            subscription_type TEXT, 
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )""")
        await db.execute("""INSERT OR IGNORE INTO points_of_interest 
            (name, address, latitude, longitude, description, category, ratings, reviews_count) 
            VALUES 
            ('Ростовский Кремль', 'Кремль, Ростов-на-Дону', 47.2315, 39.7233, 'Исторический памятник', 'historical', 4.9, 120), 
            ('Парк Горького', 'Центральный парк, Ростов-на-Дону', 47.2332, 39.7267, 'Зеленая зона для отдыха', 'park', 4.5, 200), 
            ('Музей Современного Искусства', 'Музейная ул., Ростов-на-Дону', 47.2301, 39.722, 'Коллекция современного искусства', 'art', 4.8, 98)""")
        await db.commit()

async def main():
    """Основная функция для запуска бота."""
    await setup_database()

    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(bot=bot, storage=storage)

    # Обработчик команды /start
    @dp.message(Command("start"))
    async def start_cmd(message: types.Message):
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.cursor() as cursor:
                await cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (message.from_user.id,))
                user = await cursor.fetchone()
                if not user:
                    await cursor.execute("INSERT INTO users (user_id, username) VALUES (?, ?)", (message.from_user.id, message.from_user.username))
                    await db.commit()
        await message.answer("Привет! Я бот-гид по Ростову-на-Дону.\nДоступные команды:\n/find_poi - Найти интересные места.\n/set_location - Установить ваше местоположение.\n/help - Помощь")
        await asyncio.sleep(0.5)

    # Обработчик команды /find_poi
    @dp.message(Command("find_poi"))
    async def find_poi_cmd(message: types.Message):
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.cursor() as cursor:
                await cursor.execute("SELECT location_lat, location_lon FROM users WHERE user_id = ?", (message.from_user.id,))
                location = await cursor.fetchone()
                if not location or not all(location):
                    await message.answer("Пожалуйста, сначала установите своё местоположение командой /set_location")
                    return
                user_lat, user_lon = location
                await cursor.execute("""SELECT name, address, description, category, ratings 
                                        FROM points_of_interest 
                                        ORDER BY ABS(latitude - ?) + ABS(longitude - ?) LIMIT 5""", (user_lat, user_lon))
                pois = await cursor.fetchall()
                if not pois:
                    await message.answer("К сожалению, поблизости не найдено интересных мест.")
                    return
                response = "🏛 Ближайшие места:\n"
                for poi in pois:
                    response += f"📍 {poi[0]}\n📮 Адрес: {poi[1]}\nℹ️ {poi[2]}\n🏷 Категория: {poi[3]}\n⭐️ Рейтинг: {poi[4]}\n"
                await message.answer(response)
        await asyncio.sleep(0.5)

    # Обработчик команды /set_location
    @dp.message(Command("set_location"))
    async def set_location_cmd(message: types.Message):
        keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        button = KeyboardButton("Отправить местоположение", request_location=True)
        keyboard.add(button)
        await message.answer("Пожалуйста, нажмите на кнопку ниже, чтобы отправить ваше местоположение:", reply_markup=keyboard)
        await asyncio.sleep(0.5)

    # Обработчик сообщения с местоположением
    @dp.message()
    async def handle_location(message: types.Message):
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.cursor() as cursor:
                await cursor.execute("UPDATE users SET location_lat = ?, location_lon = ? WHERE user_id = ?",
                                     (message.location.latitude, message.location.longitude, message.from_user.id))
                await db.commit()
        await message.answer("✅ Ваше местоположение сохранено!\nТеперь вы можете использовать команду /find_poi для поиска интересных мест поблизости.", reply_markup=ReplyKeyboardRemove())
        await asyncio.sleep(0.5)

    async def on_startup(dispatcher):
        pass

    async def on_shutdown(dispatcher):
        try:
            await dispatcher.storage.close()
            await dispatcher.storage.wait_closed()
            await bot.close()
        except TelegramRetryAfter as e:
            print(f"Telegram RetryAfter exception caught during shutdown: {e}")
            await asyncio.sleep(e.retry_after)
        except Exception as e:
            print(f"An unexpected error occurred during shutdown: {e}")

    await bot.delete_webhook()
    try:
        await bot.get_me()
        print("Bot initialized successfully.")
        await dp.start_polling(on_startup=on_startup, on_shutdown=on_shutdown)
    except Exception as e:
        print(f"An error occurred: {e}")
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())
