import os
import time
import logging
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW_MINUTES", "1")) * 60

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    return _redis


async def check_rate_limit(user_id: str) -> tuple[bool, int]:
    r = await get_redis()
    now = int(time.time())
    window_key = f"ratelimit:{user_id}:{now // RATE_LIMIT_WINDOW}"

    pipe = r.pipeline()
    pipe.incr(window_key)
    pipe.expire(window_key, RATE_LIMIT_WINDOW + 60)
    count, _ = await pipe.execute()

    if count > RATE_LIMIT_REQUESTS:
        return False, 429

    return True, 200


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.close()
        _redis = None
