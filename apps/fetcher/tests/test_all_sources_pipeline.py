import pytest
from unittest.mock import patch
from apps.sources.management.commands.seed_sources import SEED_SOURCES
from apps.sources.models import Source
from apps.fetcher.rss import FeedEntry
from apps.fetcher.tasks import fetch_source
from apps.fetcher.models import PipelineLog


@pytest.fixture(autouse=True)
def seed_all_sources(db):
    """Seed all sources in the test database."""
    from django.core.management import call_command
    call_command("seed_sources")


@patch("apps.fetcher.tasks.extract_from_text")
@patch("apps.fetcher.tasks.extract_article_text")
@patch("apps.fetcher.tasks.is_new_url")
@patch("apps.fetcher.tasks.discover_article_links")
@patch("apps.fetcher.tasks.fetch_rss")
def test_pipeline_all_sources(
    mock_fetch_rss,
    mock_discover_links,
    mock_is_new_url,
    mock_extract_article_text,
    mock_extract_from_text,
    db,
):
    mock_fetch_rss.return_value = [
        FeedEntry(
            link="https://example.com/rss-test-post",
            title="RSS Post Title",
            published_at=None,
            summary="RSS summary",
        )
    ]
    mock_discover_links.return_value = [
        "https://example.com/scraped-test-post"
    ]
    mock_is_new_url.return_value = True
    mock_extract_article_text.return_value = "Article body text content"
    mock_extract_from_text.return_value = {
        "is_valid_news": True,
        "title": "Extracted AI Title",
        "author": "AI Author",
        "published_at": None,
        "summary": "AI Generated summary",
        "tags": ["ai", "news"],
        "missing_fields": [],
        "invalid_reason": None,
    }

    sources = Source.objects.filter(is_active=True)
    assert len(sources) == len(SEED_SOURCES)

    for source in sources:
        saved_count = fetch_source(source.id)
        
        # Verify the pipeline ran and logged the run
        log = PipelineLog.objects.filter(source=source).first()
        assert log is not None
        assert log.status == "success"
        assert log.articles_scraped == 1
        assert log.articles_saved == 1
        assert log.finished_at is not None
        
        # Verify the database records
        from apps.posts.models import Post
        if source.rss_url:
            post = Post.objects.filter(original_url="https://example.com/rss-test-post").first()
        else:
            post = Post.objects.filter(original_url="https://example.com/scraped-test-post").first()
        
        assert post is not None
        assert post.source == source
        assert post.title == "Extracted AI Title"
        
        # Clear database posts and logs for next source's isolation
        Post.objects.all().delete()
        PipelineLog.objects.all().delete()
