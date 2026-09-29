#!/usr/bin/env python
import os
import sys
import django

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "booktrailer_leads.settings")
os.environ["GROQ_MODEL"] = "llama-3.1-8b-instant"
django.setup()

from django.conf import settings
from leadfinder.services.crawl.safe_fetch import safe_fetch, candidate_author_pages
from leadfinder.services.crawl.extract_text import extract_visible_text, extract_page_title
from leadfinder.services.crawl.extract_links import extract_links
from leadfinder.services.ai.extract_contact import extract_contact_data

def scrape_and_extract(url: str, author_name: str, book_title: str):
    print("=" * 80)
    print(f"SCRAPING AND EXTRACTING FOR AUTHOR: {author_name}")
    print(f"Book: {book_title}")
    print(f"Target Website: {url}")
    print("=" * 80)

    # 1. Generate candidate pages
    pages = candidate_author_pages(url)
    print(f"Generated candidate pages to check: {pages}")

    crawled_text = ""
    crawled_links = []
    page_source_url = None

    # Limit to top 5 pages to respect limits and avoid excessive requests
    max_pages = min(int(getattr(settings, "APP_MAX_AUTHOR_PAGES_TO_CRAWL", 5)), len(pages))
    
    print(f"\nCrawling up to {max_pages} pages...")
    for idx, page_url in enumerate(pages[:max_pages]):
        print(f"[{idx+1}/{max_pages}] Fetching: {page_url}...")
        fetched = safe_fetch(page_url)
        if not fetched:
            print(f"  -> Failed to fetch or rejected by safety/robots rules: {page_url}")
            continue
        
        if fetched.status_code >= 400:
            print(f"  -> Error status code: {fetched.status_code}")
            continue
        
        print(f"  -> Successfully fetched (status: {fetched.status_code})")
        if not page_source_url:
            page_source_url = fetched.url
            
        title = extract_page_title(fetched.html)
        text = extract_visible_text(fetched.html)
        links = extract_links(fetched.html, fetched.url)
        
        crawled_text = f"{crawled_text}\n{text}"[:12000]
        for link in links:
            if link not in crawled_links:
                crawled_links.append(link)
                
    print(f"\nCrawling complete. Extracted text size: {len(crawled_text)} characters.")
    print(f"Extracted unique links: {len(crawled_links)}")
    
    if not crawled_text.strip():
        print("[WARNING] No text could be successfully crawled from any pages.")
        return

    # 2. Extract contact data using AI/Groq
    print("\nRunning Groq AI-backed Contact Extraction...")
    try:
        extraction = extract_contact_data(
            author_name=author_name,
            book_title=book_title,
            website_url=url,
            page_url=page_source_url or url,
            visible_text=crawled_text,
            links=crawled_links,
            use_ai=True,
        )
        
        print("\n" + "=" * 80)
        print("EXTRACTION RESULTS:")
        print("=" * 80)
        print(f"Canonical Website:     {extraction.canonical_website}")
        print(f"Contact Page URL:      {extraction.contact_page_url}")
        print(f"Direct Author Email:   {extraction.public_email}")
        print(f"Direct Author Phone:   {extraction.public_phone}")
        print(f"Location:              {extraction.location}")
        print(f"Instagram:             {extraction.instagram_url}")
        print(f"Facebook:              {extraction.facebook_url}")
        print(f"TikTok:                {extraction.tiktok_url}")
        print(f"YouTube:               {extraction.youtube_url}")
        print(f"LinkedIn:              {extraction.linkedin_url}")
        print(f"Publisher URL:         {extraction.publisher_url}")
        print(f"Agent Name:            {extraction.agent_name}")
        print(f"Agent/Rep Email:       {extraction.representation_email}")
        print(f"Publicist Email:       {extraction.publicist_email}")
        print(f"Overall Confidence:    {extraction.confidence}")
        print(f"Warnings:              {extraction.warnings}")
        print("\nEvidence:")
        for idx, item in enumerate(extraction.evidence):
            print(f"  {idx+1}. Field: {item.get('field')}")
            print(f"     Value: {item.get('value')}")
            print(f"     Source URL: {item.get('source_url')}")
            print(f"     Confidence: {item.get('confidence')}")
            print(f"     Reason: {item.get('reason')}")
            print("-" * 40)
            
    except Exception as e:
        print(f"[ERROR] Failed to run Groq extraction: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Let's scrape Adrian Tchaikovsky's official website!
    scrape_and_extract(
        url="https://adriantchaikovsky.com",
        author_name="Adrian Tchaikovsky",
        book_title="Children of Time"
    )
