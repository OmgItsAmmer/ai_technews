#!/usr/bin/env python
import os
import sys
import django

# Initialize Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
django.setup()

from apps.sources.models import Source
from apps.fetcher.rss import fetch_rss
from apps.fetcher.scraper import discover_article_links, extract_article_text
from apps.extractor.service import extract_from_text

# Reconfigure stdout to use UTF-8 (handles special characters on Windows CLI)
if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding='utf-8')

def main():
    # Make sure sources are seeded in the database
    from django.core.management import call_command
    call_command("seed_sources")

    sources = Source.objects.filter(is_active=True).order_by('name')
    print(f"Found {len(sources)} active sources to process.\n")

    for idx, source in enumerate(sources, 1):
        print("\n" + "="*80)
        print(f"SOURCE {idx} OF {len(sources)}: {source.name}")
        print(f"Homepage: {source.homepage_url}")
        if source.rss_url:
            print(f"RSS Feed: {source.rss_url}")
        print("="*80)

        # Step 1: Discover / fetch articles
        try:
            if source.rss_url:
                print("STEP 1: Fetching and parsing RSS feed...")
                entries = fetch_rss(source.rss_url)
                if not entries:
                    print("  - [Info] No entries found in the RSS feed.")
                    continue
                entry = entries[0]
                url = entry.link
                title = entry.title
            else:
                print("STEP 1: Scraping homepage to discover article links...")
                links = discover_article_links(source.homepage_url)
                if not links:
                    print("  - [Info] No links discovered on the homepage.")
                    continue
                url = links[0]
                title = url
        except Exception as e:
            print(f"  - [Error] Failed to get entries: {e}")
            continue

        print(f"  - Found candidate article: {title}")
        print(f"  - Link: {url}")

        # Step 2: Downloading and extracting body text
        print("\nSTEP 2: Downloading and extracting body text from the article link...")
        try:
            article_text = extract_article_text(url)
            if not article_text:
                print("  - [Warning] Could not extract text from the webpage.")
                continue
            print(f"  - Extracted {len(article_text)} characters.")
        except Exception as e:
            print(f"  - [Error] Scraping failed: {e}")
            continue

        # Step 3: Running LLM summary
        print("\nSTEP 3: Sending article content to local LLM for metadata and summarization...")
        try:
            result = extract_from_text(article_text)
            
            # Print structured LLM results
            print("\nSTEP 4: LLM Summarization and Metadata Extraction Results:")
            print(f"  - Is Tech/AI News?:  {result['is_valid_news']}")
            print(f"  - Title (LLM):    {result['title']}")
            print(f"  - Author (LLM):   {result['author']}")
            print(f"  - Published (LLM):{result['published_at']}")
            print(f"  - Tags:           {', '.join(result['tags'])}")
            print("\n  - Summary:")
            print(f"    {result['summary']}")
            if result.get('invalid_reason'):
                print(f"  - Invalid Reason: {result['invalid_reason']}")
        except Exception as e:
            print(f"  - [Error] LLM Extraction failed: {e}")
        
        print("\n" + "-"*80 + "\n")

if __name__ == "__main__":
    main()
