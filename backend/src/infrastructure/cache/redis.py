from redis.asyncio import ConnectionPool, Redis

from src.core.config import settings

_pool: ConnectionPool | None = None


async def init_redis() -> None:
    global _pool
    _pool = ConnectionPool.from_url(settings.REDIS_URL, decode_responses=True)


async def close_redis() -> None:
    if _pool:
        await _pool.disconnect()


def get_redis() -> Redis:  # type: ignore[type-arg]
    if _pool is None:
        raise RuntimeError("Redis pool not initialised")
    return Redis(connection_pool=_pool)
