from unittest.mock import MagicMock, patch

import pytest

from apps.fetcher.rss import FeedEntry
from apps.fetcher.tasks import _process_source, fetch_all_sources, fetch_source
from apps.sources.models import Source, SourceType


@pytest.fixture
def source(db):
    return Source.objects.create(
        name="Test Source",
        homepage_url="https://example.com/",
        rss_url="https://example.com/feed.xml",
        source_type=SourceType.BLOG,
        badge_label="Blog",
        is_active=True,
    )


@patch("apps.fetcher.tasks.extract_from_text")
@patch("apps.fetcher.tasks.extract_article_text")
@patch("apps.fetcher.tasks.is_new_url")
@patch("apps.fetcher.tasks.fetch_rss")
def test_process_source_saves_valid_pending_post(
    mock_fetch_rss,
    mock_is_new_url,
    mock_extract_article_text,
    mock_extract_from_text,
    source,
):
    mock_fetch_rss.return_value = [
        FeedEntry(
            link="https://example.com/new-post",
            title="Feed Title",
            published_at=None,
            summary="snippet",
        )
    ]
    mock_is_new_url.return_value = True
    mock_extract_article_text.return_value = "Full article body"
    mock_extract_from_text.return_value = {
        "is_valid_news": True,
        "title": "Extracted Title",
        "author": "Author",
        "published_at": None,
        "summary": "AI summary",
        "tags": ["llms"],
        "missing_fields": [],
        "invalid_reason": None,
    }

    saved = _process_source(source)

    assert saved == 1
    source.refresh_from_db()
    assert source.last_fetched_at is not None

    from apps.posts.models import Post

    post = Post.objects.get(original_url="https://example.com/new-post")
    assert post.status == "pending"
    assert post.title == "Extracted Title"
    assert post.raw_content == "Full article body"
    assert post.tags == ["llms"]


@patch("apps.fetcher.tasks.extract_from_text")
@patch("apps.fetcher.tasks.extract_article_text")
@patch("apps.fetcher.tasks.is_new_url")
@patch("apps.fetcher.tasks.fetch_rss")
def test_process_source_skips_duplicate_urls(
    mock_fetch_rss,
    mock_is_new_url,
    mock_extract_article_text,
    mock_extract_from_text,
    source,
):
    mock_fetch_rss.return_value = [
        FeedEntry(
            link="https://example.com/dup",
            title="Dup",
            published_at=None,
            summary="",
        )
    ]
    mock_is_new_url.return_value = False

    saved = _process_source(source)

    assert saved == 0
    mock_extract_article_text.assert_not_called()
    mock_extract_from_text.assert_not_called()


@patch("apps.fetcher.tasks.extract_from_text")
@patch("apps.fetcher.tasks.extract_article_text")
@patch("apps.fetcher.tasks.is_new_url")
@patch("apps.fetcher.tasks.fetch_rss")
def test_process_source_skips_invalid_news(
    mock_fetch_rss,
    mock_is_new_url,
    mock_extract_article_text,
    mock_extract_from_text,
    source,
):
    mock_fetch_rss.return_value = [
        FeedEntry(
            link="https://example.com/not-news",
            title="Not News",
            published_at=None,
            summary="",
        )
    ]
    mock_is_new_url.return_value = True
    mock_extract_article_text.return_value = "body"
    mock_extract_from_text.return_value = {
        "is_valid_news": False,
        "title": "",
        "author": None,
        "published_at": None,
        "summary": "",
        "tags": [],
        "missing_fields": [],
        "invalid_reason": "Not tech news",
    }

    saved = _process_source(source)
    assert saved == 0


@patch("apps.fetcher.tasks.discover_article_links")
def test_process_source_uses_scraper_when_no_rss(mock_discover, source):
    source.rss_url = None
    source.save(update_fields=["rss_url"])

    mock_discover.return_value = []

    saved = _process_source(source)
    assert saved == 0
    mock_discover.assert_called_once_with(source.homepage_url)


@patch("apps.fetcher.tasks.fetch_source.delay")
def test_fetch_all_sources_dispatches_active_sources(mock_delay, source, db):
    Source.objects.create(
        name="Inactive",
        homepage_url="https://inactive.example/",
        rss_url="https://inactive.example/feed.xml",
        source_type=SourceType.MEDIA,
        badge_label="Media",
        is_active=False,
    )

    result = fetch_all_sources()

    assert result == {"dispatched": 1}
    mock_delay.assert_called_once_with(source.id)


@patch("apps.fetcher.tasks._process_source")
def test_fetch_source_has_retry_configuration(mock_process, source):
    assert fetch_source.max_retries == 3
    assert fetch_source.default_retry_delay == 300

    mock_process.return_value = 2
    result = fetch_source(source.id)
    assert result == 2
