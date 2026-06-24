from datetime import datetime
from unittest.mock import MagicMock, patch

from apps.fetcher.rss import FeedEntry, fetch_rss


def _make_parsed_feed(entries):
    parsed = MagicMock()
    parsed.entries = entries
    return parsed


@patch("apps.fetcher.rss.feedparser.parse")
def test_fetch_rss_returns_feed_entries(mock_parse):
    mock_parse.return_value = _make_parsed_feed(
        [
            {
                "link": "https://example.com/post-1",
                "title": "First Post",
                "published": "Mon, 01 Jan 2024 12:00:00 GMT",
                "summary": "Short summary",
            }
        ]
    )

    entries = fetch_rss("https://example.com/feed.xml")

    assert len(entries) == 1
    assert entries[0] == FeedEntry(
        link="https://example.com/post-1",
        title="First Post",
        published_at=datetime(2024, 1, 1, 12, 0, 0),
        summary="Short summary",
    )


@patch("apps.fetcher.rss.feedparser.parse")
def test_fetch_rss_skips_entries_without_link_or_title(mock_parse):
    mock_parse.return_value = _make_parsed_feed(
        [
            {"link": "", "title": "No Link"},
            {"link": "https://example.com/x", "title": ""},
            {"link": "https://example.com/ok", "title": "Valid"},
        ]
    )

    entries = fetch_rss("https://example.com/feed.xml")
    assert len(entries) == 1
    assert entries[0].title == "Valid"


@patch("apps.fetcher.rss.feedparser.parse")
def test_fetch_rss_handles_malformed_dates(mock_parse):
    mock_parse.return_value = _make_parsed_feed(
        [
            {
                "link": "https://example.com/post",
                "title": "Bad Date",
                "published": "not-a-real-date",
            }
        ]
    )

    entries = fetch_rss("https://example.com/feed.xml")
    assert entries[0].published_at is None


@patch("apps.fetcher.rss.feedparser.parse")
def test_fetch_rss_uses_description_when_summary_missing(mock_parse):
    mock_parse.return_value = _make_parsed_feed(
        [
            {
                "link": "https://example.com/post",
                "title": "Desc Post",
                "description": "From description field",
            }
        ]
    )

    entries = fetch_rss("https://example.com/feed.xml")
    assert entries[0].summary == "From description field"
