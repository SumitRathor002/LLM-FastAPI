from collections.abc import AsyncGenerator

from redis.asyncio import ConnectionPool, Redis

import redis.asyncio as aioredis
from ..config import settings
from ...schemas.chat import ChatStatus


pool: ConnectionPool | None = None
client: Redis | None = None


# Redis key helpers
def status_key(chat_uuid: str) -> str: 
    return f"chat:status:{chat_uuid}"

def buffer_key(chat_uuid: str) -> str: 
    return f"chat:buffer:{chat_uuid}"


# Small Redis helpers
async def set_status(r: aioredis.Redis, uuid: str, s: ChatStatus) -> None:
    await r.set(status_key(uuid), s.value, ex=settings.REDIS_TTL_S)


async def get_status(r: aioredis.Redis, uuid: str) -> ChatStatus | None:
    val = await r.get(status_key(uuid))
    if val is None:
        return None
    return ChatStatus(val.decode() if isinstance(val, bytes) else val)



async def async_get_redis() -> AsyncGenerator[Redis, None]:
    """Get a Redis client from the pool for each request."""
    client = Redis(connection_pool=pool)
    try:
        yield client
    finally:
        await client.aclose()  # type: ignore


