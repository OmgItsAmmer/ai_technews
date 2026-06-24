import pytest
from apps.fetcher.rss import fetch_rss
from apps.fetcher.scraper import discover_article_links, extract_article_text

@pytest.mark.integration
def test_fetch_rss_integration():
    """
    Component tested: RSS Parser (fetch_rss)
    Verifies that the parser can fetch and parse XML structure from a live, real-world RSS feed 
    and successfully map items to FeedEntry objects with links, titles, and content.
    """
    rss_url = "https://news.ycombinator.com/rss"
    entries = fetch_rss(rss_url)
    
    # We should get back a list of feed entries
    assert isinstance(entries, list)
    assert len(entries) > 0
    
    # Ensure fields are correctly populated from the live XML
    first = entries[0]
    assert first.link.startswith("http")
    assert len(first.title) > 0


@pytest.mark.integration
def test_discover_article_links_integration():
    """
    Component tested: Link Discovery Scraper (discover_article_links)
    Verifies that the scraper can download an actual webpage, parse the HTML anchors,
    filter out external links, and compile a list of same-domain absolute URLs.
    """
    url = "https://www.djangoproject.com/"
    links = discover_article_links(url, max_links=5)
    
    assert isinstance(links, list)
    assert len(links) > 0
    for link in links:
        assert link.startswith("https://www.djangoproject.com")


@pytest.mark.integration
def test_extract_article_text_integration():
    """
    Component tested: Article Content Extractor (extract_article_text)
    Verifies that the content extraction pipelines (newspaper3k & readability-lxml fallback)
    can request a live web resource and extract clean, readable text from the body,
    adhering to the character length configuration limit.
    """
    url = "https://example.com"
    content = extract_article_text(url, max_chars=100)
    
    assert isinstance(content, str)
    assert "Example Domain" in content
    assert len(content) <= 100
