"""
Quick diagnosis: does Open Library actually return results?
"""
import django, os, sys
sys.path.insert(0, 'd:/lead-scraping/django/booktrailer_leads')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'booktrailer_leads.settings')
django.setup()

import requests

print("=== TEST 1: Open Library with publish_year param ===")
resp = requests.get(
    "https://openlibrary.org/search.json",
    params={"q": "children book illustration", "publish_year": "2025", "limit": 5,
            "fields": "title,author_name,isbn,first_publish_year,publish_year"},
    timeout=15
)
data = resp.json()
print(f"  Status: {resp.status_code}, numFound: {data.get('numFound',0)}, docs: {len(data.get('docs',[]))}")
for d in data.get("docs", [])[:3]:
    print(f"  isbn={d.get('isbn',[''])[0] if d.get('isbn') else 'NONE'} title={d.get('title','')[:50]}")

print("\n=== TEST 2: Open Library NO year filter ===")
resp2 = requests.get(
    "https://openlibrary.org/search.json",
    params={"q": "children book illustration", "limit": 10,
            "fields": "title,author_name,isbn,first_publish_year,publish_year"},
    timeout=15
)
data2 = resp2.json()
print(f"  Status: {resp2.status_code}, numFound: {data2.get('numFound',0)}, docs: {len(data2.get('docs',[]))}")
for d in data2.get("docs", [])[:5]:
    isbns = d.get("isbn", [])
    print(f"  isbn={isbns[0] if isbns else 'NONE'} pub_year={d.get('publish_year',[])} title={d.get('title','')[:40]}")

print("\n=== TEST 3: Open Library provider call ===")
from leadfinder.services.books.open_library_provider import search_openlibrary
results = search_openlibrary("children book illustration", year_start=2025, year_end=2026, max_books=10)
print(f"  Results from provider: {len(results)}")
for r in results[:5]:
    print(f"  {r}")

print("\n=== TEST 4: DDG HTML scraper quick test ===")
from leadfinder.services.search.ddgs_html_provider import DDGHTMLSearchProvider
from leadfinder.services.amazon.amazon_url_parser import extract_asin, is_amazon_url
ddg = DDGHTMLSearchProvider(delay=0.2)
results2 = ddg.search("site:amazon.com children book illustration 2025", max_results=10)
print(f"  DDG results: {len(results2)}")
for r in results2[:5]:
    asin = extract_asin(r.url) if is_amazon_url(r.url) else None
    print(f"  asin={asin} url={r.url[:70]}")
