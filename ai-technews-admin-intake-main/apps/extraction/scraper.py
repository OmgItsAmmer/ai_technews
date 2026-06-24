import httpx
from bs4 import BeautifulSoup
from readability import Document
from newspaper import Article
import logging

logger = logging.getLogger(__name__)

def fetch_and_extract(url: str) -> str:
    """
    Fetches article text from url using newspaper3k,
    falling back to readability-lxml + BeautifulSoup if newspaper3k fails.
    Capped at 8000 characters.
    """
    # 1. Try newspaper3k first
    try:
        article = Article(url)
        article.download()
        article.parse()
        text = article.text.strip()
        if text:
            return text[:8000]
    except Exception as e:
        logger.warning(f"Newspaper3k extraction failed for {url}: {e}")

    # 2. Fallback to readability-lxml + BeautifulSoup
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        response = httpx.get(url, headers=headers, follow_redirects=True, timeout=10.0)
        response.raise_for_status()
        
        doc = Document(response.text)
        summary_html = doc.summary()
        
        soup = BeautifulSoup(summary_html, "html.parser")
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Get text and clean up whitespace
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = "\n".join(chunk for chunk in chunks if chunk).strip()
        
        if text:
            return text[:8000]
    except Exception as e:
        logger.error(f"Readability fallback extraction failed for {url}: {e}")
        
    return ""
