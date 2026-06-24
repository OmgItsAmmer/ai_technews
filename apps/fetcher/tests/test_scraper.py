from unittest.mock import MagicMock, patch

import httpx

from apps.fetcher.scraper import discover_article_links, extract_article_text


HOMEPAGE_HTML = """
<html>
  <body>
    <a href="/blog/post-1">Post 1</a>
    <a href="https://example.com/blog/post-2">Post 2</a>
    <a href="https://other.com/post">External</a>
    <a href="#section">Anchor</a>
    <a href="mailto:test@example.com">Email</a>
  </body>
</html>
"""


@patch("apps.fetcher.scraper.httpx.get")
def test_discover_article_links_returns_same_domain_links(mock_get):
    mock_response = MagicMock()
    mock_response.text = HOMEPAGE_HTML
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    links = discover_article_links("https://example.com/")

    assert links == [
        "https://example.com/blog/post-1",
        "https://example.com/blog/post-2",
    ]
    from apps.fetcher.scraper import DEFAULT_HEADERS
    mock_get.assert_called_once_with(
        "https://example.com/", headers=DEFAULT_HEADERS, timeout=30.0, follow_redirects=True
    )


@patch("apps.fetcher.scraper.httpx.get")
def test_discover_article_links_caps_at_max_links(mock_get):
    anchors = "".join(f'<a href="/post-{i}">P{i}</a>' for i in range(50))
    mock_response = MagicMock()
    mock_response.text = f"<html><body>{anchors}</body></html>"
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    links = discover_article_links("https://example.com/", max_links=10)
    assert len(links) == 10


@patch("apps.fetcher.scraper._extract_with_readability")
@patch("apps.fetcher.scraper._extract_with_newspaper")
def test_extract_article_text_uses_newspaper_first(mock_newspaper, mock_readability):
    mock_newspaper.return_value = "Newspaper body text"
    text = extract_article_text("https://example.com/article")
    assert text == "Newspaper body text"
    mock_readability.assert_not_called()


@patch("apps.fetcher.scraper._extract_with_readability")
@patch("apps.fetcher.scraper._extract_with_newspaper")
def test_extract_article_text_falls_back_to_readability(mock_newspaper, mock_readability):
    mock_newspaper.side_effect = RuntimeError("download failed")
    mock_readability.return_value = "Readability body text"
    text = extract_article_text("https://example.com/article")
    assert text == "Readability body text"


@patch("apps.fetcher.scraper._extract_with_readability")
@patch("apps.fetcher.scraper._extract_with_newspaper")
def test_extract_article_text_caps_length(mock_newspaper, mock_readability):
    mock_newspaper.return_value = "x" * 10000
    text = extract_article_text("https://example.com/article", max_chars=8000)
    assert len(text) == 8000


@patch("apps.fetcher.scraper.httpx.get")
def test_discover_article_links_raises_on_http_error(mock_get):
    mock_get.side_effect = httpx.HTTPError("network down")
    try:
        discover_article_links("https://example.com/")
        raised = False
    except httpx.HTTPError:
        raised = True
    assert raised
