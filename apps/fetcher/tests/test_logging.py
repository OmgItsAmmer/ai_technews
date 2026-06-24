from unittest.mock import MagicMock, patch
import pytest
from django.utils import timezone
from apps.fetcher.models import PipelineLog
from apps.fetcher.rss import FeedEntry
from apps.fetcher.tasks import fetch_source
from apps.sources.models import Source, SourceType


@pytest.fixture
def source(db):
    return Source.objects.create(
        name="Log Test Source",
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
def test_fetch_source_creates_pipeline_log_success(
    mock_fetch_rss,
    mock_is_new_url,
    mock_extract_article_text,
    mock_extract_from_text,
    source,
):
    mock_fetch_rss.return_value = [
        FeedEntry(
            link="https://example.com/log-post-1",
            title="Log Article Title",
            published_at=None,
            summary="",
        )
    ]
    mock_is_new_url.return_value = True
    mock_extract_article_text.return_value = "Body contents"
    mock_extract_from_text.return_value = {
        "is_valid_news": True,
        "title": "Extracted Title",
        "author": "Author",
        "published_at": None,
        "summary": "AI summary",
        "tags": ["logging"],
        "missing_fields": [],
        "invalid_reason": None,
    }

    result = fetch_source(source.id)
    assert result == 1

    # Verify log is in db
    log = PipelineLog.objects.filter(source=source).first()
    assert log is not None
    assert log.status == "success"
    assert log.articles_scraped == 1
    assert log.articles_saved == 1
    assert log.finished_at is not None
    assert log.error_message is None
    
    # Check details JSON structure
    details = log.details
    assert "articles" in details
    assert len(details["articles"]) == 1
    article = details["articles"][0]
    assert article["url"] == "https://example.com/log-post-1"
    assert article["steps"]["deduplication"]["status"] == "success"
    assert article["steps"]["scraping"]["status"] == "success"
    assert article["steps"]["metadata_extraction"]["status"] == "success"
    assert article["steps"]["storage"]["status"] == "saved"


@patch("apps.fetcher.tasks._process_source")
def test_fetch_source_logs_failure_on_exception(mock_process, source):
    mock_process.side_effect = Exception("Catastrophic connection failure")

    with pytest.raises(Exception):
        fetch_source(source.id)

    log = PipelineLog.objects.filter(source=source).first()
    assert log is not None
    assert log.status == "failed"
    assert "Catastrophic connection failure" in log.error_message
    assert log.finished_at is not None
