from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from src.core.config import settings

_client: AsyncIOMotorClient | None = None  # type: ignore[type-arg]


async def init_mongo() -> None:
    global _client
    _client = AsyncIOMotorClient(settings.MONGODB_URL)


async def close_mongo() -> None:
    if _client:
        _client.close()


def get_mongo_db() -> AsyncIOMotorDatabase:  # type: ignore[type-arg]
    if _client is None:
        raise RuntimeError("MongoDB client not initialised")
    return _client[settings.MONGODB_DB]
