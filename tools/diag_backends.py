"""
Test DDGS backends individually to find which works.
"""
import django, os, sys, time
sys.path.insert(0, 'd:/lead-scraping/django/booktrailer_leads')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'booktrailer_leads.settings')
django.setup()

from ddgs import DDGS
from leadfinder.services.amazon.amazon_url_parser import extract_asin, is_amazon_url

QUERY = "children book illustration amazon 2025"
BACKENDS = ["auto", "html", "lite", "api"]

for backend in BACKENDS:
    print(f"\n[BACKEND: {backend}]")
    try:
        with DDGS(timeout=15, verify=False) as ddgs:
            results = list(ddgs.text(QUERY, max_results=5, backend=backend))
        print(f"  Results: {len(results)}")
        for r in results[:3]:
            url = r.get("href", r.get("url", ""))
            is_amz = is_amazon_url(url)
            asin = extract_asin(url) if is_amz else None
            print(f"  {'[AMZ]' if is_amz else '     '} {url[:80]}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
    time.sleep(1)
