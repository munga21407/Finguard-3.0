from redis.asyncio import ConnectionPool, Redis

from src.core.config import settings

# DB 0 — Celery broker / general cache
_pool: ConnectionPool | None = None
# DB 1 — JWT blacklist + email verification tokens
_auth_pool: ConnectionPool | None = None
# DB 2 — per-IP rate-limit counters (slowapi)
_rate_limit_pool: ConnectionPool | None = None


async def init_redis() -> None:
    global _pool, _auth_pool, _rate_limit_pool
    _pool = ConnectionPool.from_url(settings.REDIS_URL, decode_responses=True)
    _auth_pool = ConnectionPool.from_url(settings.AUTH_REDIS_URL, decode_responses=True)
    _rate_limit_pool = ConnectionPool.from_url(settings.RATE_LIMIT_REDIS_URL, decode_responses=True)


async def close_redis() -> None:
    for pool in (_pool, _auth_pool, _rate_limit_pool):
        if pool:
            await pool.disconnect()


def get_redis() -> Redis:  # type: ignore[type-arg]
    if _pool is None:
        raise RuntimeError("Redis pool not initialised")
    return Redis(connection_pool=_pool)


def get_auth_redis() -> Redis:  # type: ignore[type-arg]
    """DB 1 — JWT blacklist and email verification tokens."""
    if _auth_pool is None:
        raise RuntimeError("Auth Redis pool not initialised")
    return Redis(connection_pool=_auth_pool)


def get_rate_limit_redis() -> Redis:  # type: ignore[type-arg]
    """DB 2 — per-IP rate-limit counters for slowapi."""
    if _rate_limit_pool is None:
        raise RuntimeError("Rate-limit Redis pool not initialised")
    return Redis(connection_pool=_rate_limit_pool)
