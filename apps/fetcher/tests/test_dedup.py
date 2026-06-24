import fakeredis
import pytest
from django.conf import settings

from apps.fetcher.dedup import is_new_url


@pytest.fixture
def redis_client():
    return fakeredis.FakeRedis(decode_responses=True)


def test_is_new_url_returns_true_for_first_seen_url(redis_client):
    assert is_new_url("https://example.com/article-1", redis_client=redis_client) is True


def test_is_new_url_returns_false_for_duplicate_url(redis_client):
    url = "https://example.com/article-2"
    assert is_new_url(url, redis_client=redis_client) is True
    assert is_new_url(url, redis_client=redis_client) is False


def test_is_new_url_different_urls_are_both_new(redis_client):
    assert is_new_url("https://example.com/a", redis_client=redis_client) is True
    assert is_new_url("https://example.com/b", redis_client=redis_client) is True


def test_is_new_url_sets_ttl_on_redis_set(redis_client):
    url = "https://example.com/article-3"
    is_new_url(url, redis_client=redis_client)
    ttl = redis_client.ttl(settings.FETCHER_DEDUP_REDIS_KEY)
    assert ttl > 0
    assert ttl <= settings.FETCHER_DEDUP_TTL_SECONDS


def test_is_new_url_hashes_are_stored_not_raw_urls(redis_client):
    url = "https://example.com/secret-article"
    is_new_url(url, redis_client=redis_client)
    members = redis_client.smembers(settings.FETCHER_DEDUP_REDIS_KEY)
    assert url not in members
    assert len(members) == 1
