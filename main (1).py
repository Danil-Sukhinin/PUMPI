import os
import asyncio
import logging
from datetime import datetime
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# --- Конфигурация ---
BOT_TOKEN = "TOKEN"  
YANDEX_MAPS_API_KEY = "TOKEN"  
DATABASE_URL = "sqlite+aiosqlite:///test.db"  

Base = declarative_base()
engine = create_async_engine(DATABASE_URL, echo=True)
Session = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

# --- Модели базы данных ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String, nullable=True)
    location = Column(JSON, default={})
    preferences = Column(JSON, default={})

class PointOfInterest(Base):
    __tablename__ = "points_of_interest"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    address = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    description = Column(String)
    category = Column(String)
    website = Column(String)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# --- Функции взаимодействия с API Яндекс.Карт ---
async def geocode(address):
    """Геокодирование адреса через API Яндекс.Карт."""
    url = "https://geocode-maps.yandex.ru/1.x/"
    params = {
        "apikey": YANDEX_MAPS_API_KEY,
        "geocode": address,
        "format": "json",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            data = await resp.json()
            try:
                pos = data["response"]["GeoObjectCollection"]["featureMember"][0]["GeoObject"]["Point"]["pos"]
                longitude, latitude = map(float, pos.split())
                return {"latitude": latitude, "longitude": longitude}
            except (KeyError, IndexError):
                return None

async def get_directions(origin, destination):
    """Поиск маршрута между двумя точками через Яндекс.Карты."""
    url = "https://router.route.maps.yandex.net/v2/route"
    headers = {"apikey": YANDEX_MAPS_API_KEY}
    params = {
        "waypoints": f"{origin['longitude']},{origin['latitude']}|{destination['longitude']},{destination['latitude']}",
        "mode": "driving",  # Возможны: "walking", "biking", "driving".
        "lang": "ru_RU",
        "format": "json",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as resp:
            data = await resp.json()
            try:
                route = data["routes"][0]
                distance = route["legs"][0]["distance"]["text"]
                duration = route["legs"][0]["duration"]["text"]
                return {"distance": distance, "duration": duration}
            except (KeyError, IndexError):
                return None

# --- Логика бота ---
async def start_command(message: types.Message, session: AsyncSession):
    """Обработчик команды /start."""
    async with session.begin():
        # Создание пользователя в базе данных, если его нет
        user = await session.execute(
            session.query(User).filter(User.telegram_id == message.from_user.id)
        )
        user = user.scalars().first()
        if not user:
            new_user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                location={},
                preferences={"category": "restaurant"},
            )
            session.add(new_user)
        await message.answer("Добро пожаловать! Я помогу вам найти интересные места и маршруты.")

async def set_location_command(message: types.Message):
    """Обработчик команды /set_location."""
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    keyboard.add(KeyboardButton("Отправить местоположение", request_location=True))
    await message.answer("Пожалуйста, отправьте ваше местоположение.", reply_markup=keyboard)

async def process_location(message: types.Message, session: AsyncSession):
    """Обработка местоположения пользователя."""
    if message.location:
        latitude = message.location.latitude
        longitude = message.location.longitude
        async with session.begin():
            user = await session.execute(
                session.query(User).filter(User.telegram_id == message.from_user.id)
            )
            user = user.scalars().first()
            if user:
                user.location = {"latitude": latitude, "longitude": longitude}
                await message.answer("Ваше местоположение сохранено!", reply_markup=ReplyKeyboardRemove())
            else:
                await message.answer("Сначала введите команду /start.")
    else:
        await message.answer("Не удалось определить ваше местоположение.")

async def find_poi_command(message: types.Message, session: AsyncSession):
    """Поиск POI (точек интереса) рядом с пользователем."""
    async with session.begin():
        user = await session.execute(
            session.query(User).filter(User.telegram_id == message.from_user.id)
        )
        user = user.scalars().first()
        if user and user.location:
            latitude = user.location["latitude"]
            longitude = user.location["longitude"]
            poi = await session.execute(
                session.query(PointOfInterest).filter(
                    PointOfInterest.latitude.between(latitude - 0.01, latitude + 0.01),
                    PointOfInterest.longitude.between(longitude - 0.01, longitude + 0.01),
                )
            )
            poi = poi.scalars().all()
            if poi:
                answer = "\n".join(
                    [f"{p.name}, {p.address}, {p.website or 'нет сайта'}" for p in poi]
                )
                await message.answer(f"Найденные места:\n{answer}")
            else:
                await message.answer("К сожалению, поблизости ничего не найдено.")
        else:
            await message.answer("Сначала укажите ваше местоположение с помощью команды /set_location.")

async def get_directions_command(message: types.Message, session: AsyncSession):
    """Получение маршрута от местоположения пользователя до заданного."""
    async with session.begin():
        user = await session.execute(
            session.query(User).filter(User.telegram_id == message.from_user.id)
        )
        user = user.scalars().first()
        if user and user.location:
            destination = {"latitude": 47.222078, "longitude": 39.720358}  # Центр Ростова-на-Дону
            directions = await get_directions(user.location, destination)
            if directions:
                distance = directions["distance"]
                duration = directions["duration"]
                await message.answer(f"Маршрут до центра города:\nРасстояние: {distance}\nВремя: {duration}")
            else:
                await message.answer("Не удалось построить маршрут.")
        else:
            await message.answer("Сначала укажите ваше местоположение с помощью команды /set_location.")

# --- Настройка бота ---
async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # Регистрация команд
    dp.message.register(start_command, commands=["start"])
    dp.message.register(set_location_command, commands=["set_location"])
    dp.message.register(process_location, content_types=["location"])
    dp.message.register(find_poi_command, commands=["find_poi"])
    dp.message.register(get_directions_command, commands=["get_directions"])

    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
