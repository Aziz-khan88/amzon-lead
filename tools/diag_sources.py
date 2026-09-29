"""
Test what actually works for finding children's book illustration ISBNs.
"""
import django, os, sys
sys.path.insert(0, 'd:/lead-scraping/django/booktrailer_leads')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'booktrailer_leads.settings')
django.setup()

import requests, re, os

KEYWORD = "children book illustration"
START = 2025
END = 2026

print("=== TEST 1: Open Library with BETTER query ===")
queries_to_try = [
    "children picture book illustration 2025",
    "illustrated children books 2025",
    "picture book 2025 illustrated",
]
for q in queries_to_try:
    resp = requests.get(
        "https://openlibrary.org/search.json",
        params={"q": q, "limit": 5, "fields": "title,author_name,isbn,publish_year,first_publish_year"},
        timeout=10
    )
    data = resp.json()
    docs_with_isbn = [d for d in data.get("docs", []) if d.get("isbn")]
    print(f"  q={q!r}")
    print(f"  numFound={data.get('numFound',0)}, withISBN={len(docs_with_isbn)}")
    for d in docs_with_isbn[:2]:
        py = d.get("publish_year", [])
        print(f"    isbn={d['isbn'][0]} title={d.get('title','')[:40]} years_sample={py[:5]}")

print("\n=== TEST 2: Google Books API ===")
gkey = os.getenv("GOOGLE_API_KEY")
print(f"  Key present: {bool(gkey)}")
if gkey:
    resp = requests.get(
        "https://www.googleapis.com/books/v1/volumes",
        params={"q": KEYWORD, "maxResults": 10, "key": gkey,
                "printType": "books", "orderBy": "newest"},
        timeout=10
    )
    data = resp.json()
    items = data.get("items", [])
    print(f"  status={resp.status_code} items={len(items)} error={data.get('error',{}).get('message','none')}")
    for item in items[:5]:
        info = item.get("volumeInfo", {})
        ids = info.get("industryIdentifiers", [])
        isbn = next((x["identifier"] for x in ids if "ISBN" in x.get("type", "")), None)
        pub = info.get("publishedDate", "?")
        print(f"    {info.get('title','')[:50]} isbn={isbn} pub={pub}")

print("\n=== TEST 3: Amazon direct search ===")
resp = requests.get(
    "https://www.amazon.com/s",
    params={"k": KEYWORD, "i": "stripbooks"},
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml",
    },
    timeout=15
)
print(f"  Amazon search status: {resp.status_code}")
if resp.status_code == 200:
    asins = list(dict.fromkeys(re.findall(r'/dp/([A-Z0-9]{10})', resp.text)))
    print(f"  ASINs found: {len(asins)} -- {asins[:10]}")
else:
    print(f"  Response size: {len(resp.content)} bytes")

print("\n=== TEST 4: Tavily search ===")
from leadfinder.services.search.tavily_provider import TavilySearchProvider
tavily = TavilySearchProvider()
print(f"  Tavily key: {bool(tavily.api_key)}")
if tavily.api_key:
    results = tavily.search(f"{KEYWORD} amazon book 2025", max_results=10)
    print(f"  Results: {len(results)}")
    from leadfinder.services.amazon.amazon_url_parser import extract_asin, is_amazon_url
    for r in results[:5]:
        asin = extract_asin(r.url) if is_amazon_url(r.url) else None
        print(f"  asin={asin} url={r.url[:70]}")
