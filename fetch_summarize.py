#!/usr/bin/env python
import os
import sys
import django

# Initialize Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
django.setup()

from apps.fetcher.rss import fetch_rss
from apps.fetcher.scraper import extract_article_text
from apps.extractor.service import extract_from_text

# Reconfigure stdout to use UTF-8 (handles special characters on Windows CLI)
if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding='utf-8')

def main():
    rss_url = "https://openai.com/news/rss.xml"
    print("\n" + "="*80)
    print("STEP 1: Fetching and parsing RSS feed...")
    print(f"URL: {rss_url}")
    print("="*80)
    
    try:
        entries = fetch_rss(rss_url)
    except Exception as e:
        print(f"Error fetching RSS feed: {e}")
        sys.exit(1)
        
    if not entries:
        print("No entries found in the RSS feed.")
        sys.exit(0)
        
    print(f"Successfully fetched {len(entries)} articles.")
    
    # We will process the top 3 articles to show details and keep token usage low
    limit = 3
    print(f"\nProcessing the top {limit} articles:\n")
    
    for idx, entry in enumerate(entries[:limit], 1):
        print("-"*80)
        print(f"ARTICLE {idx} OF {limit}")
        print("-"*80)
        
        # Step 2: Show RSS metadata
        print("STEP 2: Reading RSS entry metadata:")
        print(f"  - Title:        {entry.title}")
        print(f"  - Link:         {entry.link}")
        print(f"  - Published At: {entry.published_at}")
        
        # Step 3: Fetching and reading body content
        print("\nSTEP 3: Downloading and extracting body text from the article link...")
        article_text = extract_article_text(entry.link)
        if not article_text:
            print("  [Warning] Could not extract text from the webpage.")
            continue
        print(f"  - Extracted {len(article_text)} characters.")
        
        # Step 4: Running LLM summary
        print("\nSTEP 4: Sending article content to GPT for metadata and summarization...")
        try:
            result = extract_from_text(article_text)
            
            # Print structured LLM results
            print("\nSTEP 5: LLM Summarization and Metadata Extraction Results:")
            print(f"  - Is Tech News?:  {result['is_valid_news']}")
            print(f"  - Title (LLM):    {result['title']}")
            print(f"  - Author (LLM):   {result['author']}")
            print(f"  - Published (LLM):{result['published_at']}")
            print(f"  - Tags:           {', '.join(result['tags'])}")
            print("\n  - Summary:")
            print(f"    {result['summary']}")
            if result['invalid_reason']:
                print(f"  - Invalid Reason: {result['invalid_reason']}")
        except Exception as e:
            print(f"  [Error] LLM Extraction failed: {e}")
        
        print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    main()
