from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from django.conf import settings
from newspaper import Article
from readability import Document


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def discover_article_links(homepage_url: str, max_links: int | None = None) -> list[str]:
    """Fetch a homepage and return up to 30 candidate article links."""
    limit = max_links or settings.FETCHER_MAX_HOMEPAGE_LINKS
    response = httpx.get(homepage_url, headers=DEFAULT_HEADERS, timeout=30.0, follow_redirects=True)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    base = urlparse(homepage_url)
    seen: set[str] = set()
    links: list[str] = []

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue

        absolute = urljoin(homepage_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc != base.netloc:
            continue

        normalized = absolute.split("#")[0].rstrip("/")
        if normalized in seen:
            continue

        seen.add(normalized)
        links.append(absolute)
        if len(links) >= limit:
            break

    return links


def _extract_with_newspaper(url: str) -> str:
    article = Article(url)
    article.download()
    article.parse()
    return (article.text or "").strip()


def _extract_with_readability(url: str) -> str:
    response = httpx.get(url, headers=DEFAULT_HEADERS, timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    doc = Document(response.text)
    soup = BeautifulSoup(doc.summary(), "html.parser")
    return soup.get_text(separator="\n", strip=True)


def extract_article_text(
    url: str,
    max_chars: int | None = None,
) -> str:
    """
    Extract clean article body text, preferring newspaper3k with readability fallback.
    Result is capped at FETCHER_MAX_ARTICLE_TEXT_CHARS (default 8000).
    """
    limit = max_chars or settings.FETCHER_MAX_ARTICLE_TEXT_CHARS
    text = ""

    try:
        text = _extract_with_newspaper(url)
    except Exception:
        text = ""

    if not text:
        try:
            text = _extract_with_readability(url)
        except Exception:
            text = ""

    return text[:limit]
