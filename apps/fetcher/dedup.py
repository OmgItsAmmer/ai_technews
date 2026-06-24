import hashlib

import redis
from django.conf import settings


def _get_redis_client() -> redis.Redis:
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def is_new_url(url: str, redis_client: redis.Redis | None = None) -> bool:
    """
    Return True if the URL has not been seen before (new), False if duplicate.

    Uses Redis SADD on a set keyed by FETCHER_DEDUP_REDIS_KEY. SADD returns 1
    when the member is new and 0 when it already existed. The set TTL is
    refreshed on each write so entries expire after 30 days.
    """
    client = redis_client or _get_redis_client()
    key = settings.FETCHER_DEDUP_REDIS_KEY
    ttl = settings.FETCHER_DEDUP_TTL_SECONDS

    added = client.sadd(key, _url_hash(url))
    if added:
        client.expire(key, ttl)
        return True

    client.expire(key, ttl)
    return False


def remove_seen_url(url: str, redis_client: redis.Redis | None = None) -> None:
    """Remove a URL hash from the Redis seen set, allowing it to be retried."""
    client = redis_client or _get_redis_client()
    key = settings.FETCHER_DEDUP_REDIS_KEY
    client.srem(key, _url_hash(url))

