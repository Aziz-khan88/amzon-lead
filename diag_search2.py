"""
Test 2: Check if DDGS works as fallback and what Tavily is doing wrong.
"""
import django, os, sys, re
sys.path.insert(0, 'd:/lead-scraping/django/booktrailer_leads')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'booktrailer_leads.settings')
django.setup()

from leadfinder.services.search.ddgs_provider import DDGSSearchProvider
from leadfinder.services.search.tavily_provider import TavilySearchProvider
from leadfinder.services.amazon.amazon_url_parser import extract_asin, is_amazon_url

print("\n=== TEST 1: DDGS Direct ===")
ddgs = DDGSSearchProvider()
q = "amazon children book illustration 2025"
try:
    results = ddgs.search(q, max_results=10)
    print(f"  Query: {q}")
    print(f"  Results: {len(results)}")
    for r in results[:5]:
        is_amz = is_amazon_url(r.url)
        asin = extract_asin(r.url) if is_amz else None
        print(f"  [{'ASIN:'+asin if asin else 'no-asin':20}] {r.url[:80]}")
except Exception as e:
    print(f"  DDGS ERROR: {e}")

print("\n=== TEST 2: Tavily direct (no site: prefix) ===")
tavily = TavilySearchProvider()
print(f"  API key present: {bool(tavily.api_key)}")
q2 = "children book illustration 2025 amazon"
try:
    results2 = tavily.search(q2, max_results=10)
    print(f"  Query: {q2}")
    print(f"  Results: {len(results2)}")
    for r in results2[:5]:
        is_amz = is_amazon_url(r.url)
        asin = extract_asin(r.url) if is_amz else None
        print(f"  [{'ASIN:'+asin if asin else 'no-asin':20}] {r.url[:80]}")
except Exception as e:
    print(f"  TAVILY ERROR: {e}")

print("\n=== TEST 3: Tavily _clean_query on site: queries ===")
raw_q = 'site:amazon.com "children book illustration" 2025'
cleaned = tavily._clean_query(raw_q)
print(f"  Raw: {raw_q}")
print(f"  Cleaned: {cleaned}")
print(f"  (Note: quotes are stripped - this is a problem!)")

print("\n=== TEST 4: DDGS with simple amazon query ===")
simple_q = "site:amazon.com children book illustration 2025"
try:
    results3 = ddgs.search(simple_q, max_results=10)
    print(f"  Query: {simple_q}")
    print(f"  Results: {len(results3)}")
    for r in results3[:5]:
        is_amz = is_amazon_url(r.url)
        asin = extract_asin(r.url) if is_amz else None
        print(f"  [{'ASIN:'+asin if asin else 'no-asin':20}] {r.url[:80]}")
except Exception as e:
    print(f"  DDGS ERROR: {e}")
