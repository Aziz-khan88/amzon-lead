"""
Full diagnostic: isbn_lookup flow analysis using DDGS only.
Run: python diag_full.py
"""
import django, os, sys, re, json, time

sys.path.insert(0, 'd:/lead-scraping/django/booktrailer_leads')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'booktrailer_leads.settings')
django.setup()

from leadfinder.services.search.ddgs_provider import DDGSSearchProvider
from leadfinder.services.amazon.amazon_url_parser import extract_asin, is_amazon_url
from leadfinder.services.pipeline.run_research import guess_title_author

ddgs = DDGSSearchProvider()

KEYWORD = "children book illustration"
START = 2025
END = 2026

print("\n" + "="*70)
print("PHASE 1: RAW DDGS QUERY TESTS")
print("="*70)

test_queries = [
    # Simple - no site: or quotes
    f"amazon {KEYWORD} {START}",
    f"amazon {KEYWORD} {START} children book",
    f"amazon {KEYWORD} {START} ISBN",
    # With site: (DDGS supports it)
    f"site:amazon.com {KEYWORD} {START}",
    f"site:amazon.com {KEYWORD} {START} paperback",
    # Without year
    f"amazon {KEYWORD} picture book",
    f"site:amazon.com {KEYWORD}",
    # Different angle
    f"{KEYWORD} amazon.com 2025",
    f"{KEYWORD} buy amazon 2025",
    f"amazon books {KEYWORD} 2025 illustrated",
]

all_found = {}  # asin -> data

for query in test_queries:
    print(f"\n  QUERY: {query}")
    try:
        results = ddgs.search(query, max_results=10)
        amazon_hits = 0
        asin_hits = 0
        for r in results:
            is_amz = is_amazon_url(r.url)
            asin = extract_asin(r.url) if is_amz else None
            year_match = re.search(r'\b(19\d{2}|20\d{2})\b', f"{r.title} {r.snippet}")
            pub_year = year_match.group(0) if year_match else None
            year_ok = True
            if pub_year:
                py = int(pub_year)
                if py < START or py > END:
                    year_ok = False

            status = ""
            if is_amz and asin:
                amazon_hits += 1
                asin_hits += 1
                status = f"ASIN={asin} year={pub_year or '?'} {'(FILTERED OUT)' if not year_ok else '(ACCEPTED)'}"
                if asin not in all_found:
                    all_found[asin] = {"title": r.title, "year": pub_year, "url": r.url}
            elif is_amz:
                amazon_hits += 1
                status = f"amazon-no-asin url={r.url[:60]}"
            else:
                status = f"non-amazon: {r.url[:60]}"
            print(f"    [{status}]")
        print(f"  => Total={len(results)}, Amazon={amazon_hits}, WithASIN={asin_hits}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
    time.sleep(0.5)

print("\n" + "="*70)
print(f"PHASE 2: UNIQUE ASINs FOUND: {len(all_found)}")
print("="*70)
for asin, data in all_found.items():
    print(f"  {asin} | year={data['year']} | {data['title'][:60]}")

print("\n" + "="*70)
print("PHASE 3: ASIN REGEX TEST")
print("="*70)
test_urls = [
    "https://www.amazon.com/dp/0711277958",
    "https://www.amazon.com/dp/0711277958/ref=sr_1_1",
    "https://www.amazon.com/Lost-Illustrajo-Mariajo/dp/0711277958/",
    "https://www.amazon.com/gp/product/0711277958",
    "https://amazon.com/dp/B0DBZV185Z?tag=abc",
    "https://www.amazon.co.uk/dp/0711277958",
    "https://www.goodreads.com/book/isbn/0711277958",
]
for url in test_urls:
    amz = is_amazon_url(url)
    asin = extract_asin(url)
    print(f"  is_amazon={amz} asin={asin} => {url[:70]}")

print("\n" + "="*70)
print("PHASE 4: guess_title_author TEST")
print("="*70)
test_snippets = [
    ("Lost: Shortlisted for Illustrator of the Year - British Book Awards 2025: Ilustrajo, Mariajo: 9780711277953", "by Mariajo Ilustrajo Published 2025"),
    ("Amazon.com: Children's Book Illustration Step by Step: 9780123456789: Smith, John", ""),
    ("VISIONS 2025 ILLUSTRATORS BOOK: PIXIV Books", "ISBN 4046841079"),
]
for title, snippet in test_snippets:
    t, a, _ = guess_title_author(title, snippet)
    print(f"  IN:  {title[:60]}")
    print(f"  OUT: title={t!r}, author={a!r}")
    print()

print("DIAGNOSTIC COMPLETE")
