import redis
from backend.config import get_settings
from datetime import datetime, timezone


settings = get_settings()
redis_pool = redis.ConnectionPool.from_url(
    str(settings.REDIS_URL), decode_responses=True, max_connections=10
)


def get_redis_client():
    return redis.Redis(connection_pool=redis_pool)


r = get_redis_client()


class LinkCache:
    @staticmethod
    def set_destination(short_code: str, original_url: str, expires_at=None):
        redis_key = f"link:{short_code}"

        if expires_at:
            ttl = int((expires_at - datetime.now(timezone.utc)).total_seconds())
            if ttl <= 0:
                return
            r.set(redis_key, original_url, ex=ttl)
        else:
            r.set(redis_key, original_url, ex=settings.MAX_TTL_SECONDS)

    @staticmethod
    def get_destination(short_code: str) -> str:
        redis_key = f"link:{short_code}"
        return r.get(redis_key)

    @staticmethod
    def invalidate(short_code: str):
        r.delete(f"link:{short_code}")


class ClickCounter:
    @staticmethod
    def record_click(short_code: str):
        redis_key = f"clicks:{short_code}"
        return r.incr(redis_key)

    @staticmethod
    def get_clicks(short_code: str) -> int:
        count = r.get(f"clicks:{short_code}")
        return int(count) if count else 0


class RateLimiter:
    @staticmethod
    def is_allowed(ip: str, limit: int = 5, window: int = 5) -> bool:
        key = f"ratelimit:{ip}"
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, window)
        count, _ = pipe.execute()
        return count <= limit


class UniqueVisitorTracker:
    @staticmethod
    def record(short_code: str, ip_hash: str):
        r.pfadd(f"uv:{short_code}", ip_hash)

    @staticmethod
    def count(short_code: str) -> int:
        return r.pfcount(f"uv:{short_code}")
