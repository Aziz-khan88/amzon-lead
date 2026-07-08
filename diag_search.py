"""
Deep diagnostic script for isbn_lookup search flow.
Run with: python diag_search.py
"""
import django
import os
import sys
import re

sys.path.insert(0, 'd:/lead-scraping/django/booktrailer_leads')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'booktrailer_leads.settings')
django.setup()

from leadfinder.services.search import get_search_provider
from leadfinder.services.amazon.amazon_url_parser import extract_asin, is_amazon_url

provider = get_search_provider()
print(f"\n{'='*60}")
print(f"PROVIDER: {provider.provider_name}")
print(f"{'='*60}\n")

KEYWORD = "children book illustration"
START_YEAR = 2025
END_YEAR = 2026

queries_to_test = [
    f'site:amazon.com "{KEYWORD}" {START_YEAR}',
    f'site:amazon.com/dp "{KEYWORD}" {START_YEAR}',
    f'amazon "{KEYWORD}" {START_YEAR} book',
    f'"{KEYWORD}" {START_YEAR} ISBN amazon',
    f'site:amazon.com "{KEYWORD}" paperback {START_YEAR}',
]

total_amazon = 0
total_with_asin = 0

for query in queries_to_test:
    print(f"\nQUERY: {query}")
    print(f"{'-'*60}")
    try:
        results = provider.search(query, max_results=10)
        print(f"  Total results returned: {len(results)}")
        amazon_count = 0
        asin_count = 0
        for r in results:
            is_amz = is_amazon_url(r.url)
            asin = extract_asin(r.url) if is_amz else None
            
            # Year check
            year_match = re.search(r'\b(19\d{2}|20\d{2})\b', f"{r.title} {r.snippet}")
            pub_year = year_match.group(0) if year_match else "unknown"
            
            status = "✓ AMAZON+ASIN" if (is_amz and asin) else ("~ amazon-no-asin" if is_amz else "✗ non-amazon")
            print(f"  [{status}] year={pub_year}")
            print(f"    URL: {r.url[:100]}")
            if is_amz:
                amazon_count += 1
                total_amazon += 1
            if asin:
                asin_count += 1
                total_with_asin += 1
        print(f"  -> Amazon URLs: {amazon_count}, With ASIN: {asin_count}")
    except Exception as e:
        print(f"  ERROR: {e}")

print(f"\n{'='*60}")
print(f"TOTALS: Amazon={total_amazon}, With ASIN={total_with_asin}")
print(f"{'='*60}\n")
