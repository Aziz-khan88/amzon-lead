"""Test Tavily and Amazon direct - both confirmed working previously."""
import django, os, sys
sys.path.insert(0, 'd:/lead-scraping/django/booktrailer_leads')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'booktrailer_leads.settings')
django.setup()

import requests, re, os

print("=== TEST 1: Tavily with clean query (no site:, no quotes) ===")
from leadfinder.services.search.tavily_provider import TavilySearchProvider
from leadfinder.services.amazon.amazon_url_parser import extract_asin, is_amazon_url

tavily = TavilySearchProvider()
print(f"  Tavily key present: {bool(tavily.api_key)}")

test_queries = [
    "amazon children picture book illustration 2025",
    "amazon picture book 2025 new release",
    "amazon.com children illustrated book 2025 buy",
    "children book illustration amazon 2025 paperback",
]

for q in test_queries:
    try:
        results = tavily.search(q, max_results=10)
        amz = [(extract_asin(r.url), r.url[:70]) for r in results if is_amazon_url(r.url) and extract_asin(r.url)]
        print(f"  q={q!r}")
        print(f"    total={len(results)}, amazon_with_asin={len(amz)}: {[a[0] for a in amz[:5]]}")
    except Exception as e:
        print(f"  ERROR: {e}")

print("\n=== TEST 2: Amazon search page via requests ===")
resp = requests.get(
    "https://www.amazon.com/s",
    params={"k": "children book illustration", "i": "stripbooks", "s": "date-desc-rank"},
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
    },
    timeout=20
)
print(f"  Status: {resp.status_code}")
if resp.status_code == 200:
    asins = list(dict.fromkeys(re.findall(r'/dp/([A-Z0-9]{10})', resp.text)))
    print(f"  ASINs found: {len(asins)}")
    print(f"  First 10: {asins[:10]}")
