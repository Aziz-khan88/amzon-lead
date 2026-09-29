"""
Test what search methods actually work with installed packages.
"""
import django, os, sys, re
sys.path.insert(0, 'd:/lead-scraping/django/booktrailer_leads')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'booktrailer_leads.settings')
django.setup()

from leadfinder.services.amazon.amazon_url_parser import extract_asin, is_amazon_url

KEYWORD = "children book illustration"
QUERY = f"amazon {KEYWORD} 2025"

print("=== TEST 1: requests + BeautifulSoup (installed) ===")
try:
    import requests
    from bs4 import BeautifulSoup
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    # DuckDuckGo HTML search
    url = "https://html.duckduckgo.com/html/"
    resp = requests.post(url, data={"q": QUERY, "b": "", "kl": "us-en"}, headers=headers, timeout=15)
    print(f"  DDG HTML status: {resp.status_code}")
    soup = BeautifulSoup(resp.text, "html.parser")
    results = soup.select(".result__url, .result__a")
    print(f"  DDG HTML links found: {len(results)}")
    for r in results[:5]:
        href = r.get("href", r.text.strip())
        print(f"    {href[:80]}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n=== TEST 2: requests to DuckDuckGo Lite ===")
try:
    import requests
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(
        "https://lite.duckduckgo.com/lite/",
        params={"q": QUERY, "kl": "us-en"},
        headers=headers, timeout=15
    )
    print(f"  DDG Lite status: {resp.status_code}, bytes={len(resp.content)}")
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    links = soup.select("a.result-link, td a")
    print(f"  Links: {len(links)}")
    for l in links[:10]:
        href = l.get("href", "")
        text = l.text.strip()[:60]
        print(f"    href={href[:80]} text={text}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n=== TEST 3: Google Custom Search (check env) ===")
import os
gkey = os.getenv("GOOGLE_API_KEY")
gcse = os.getenv("GOOGLE_CSE_ID")
print(f"  GOOGLE_API_KEY: {'SET' if gkey else 'NOT SET'}")
print(f"  GOOGLE_CSE_ID:  {'SET' if gcse else 'NOT SET'}")
print(f"  TAVILY_API_KEY: {'SET' if os.getenv('TAVILY_API_KEY') else 'NOT SET'}")
print(f"  BRAVE_API_KEY:  {'SET' if os.getenv('BRAVE_API_KEY') else 'NOT SET'}")
print(f"  SEARCH_PROVIDER: {os.getenv('SEARCH_PROVIDER', 'not set (defaults ddgs)')}")

print("\n=== TEST 4: Try Google Books API with API key ===")
try:
    import requests
    gbook_key = os.getenv("GOOGLE_BOOKS_API_KEY") or os.getenv("GOOGLE_API_KEY")
    params = {
        "q": f"{KEYWORD}",
        "maxResults": 10,
        "printType": "books",
        "langRestrict": "en",
    }
    if gbook_key:
        params["key"] = gbook_key
    resp = requests.get("https://www.googleapis.com/books/v1/volumes", params=params, timeout=10)
    print(f"  Google Books status: {resp.status_code}")
    data = resp.json()
    items = data.get("items", [])
    print(f"  Items returned: {len(items)}")
    for item in items[:3]:
        info = item.get("volumeInfo", {})
        ids = info.get("industryIdentifiers", [])
        isbn = next((x["identifier"] for x in ids if "ISBN" in x.get("type","")), None)
        pub = info.get("publishedDate","?")
        print(f"    {info.get('title','?')[:50]} | isbn={isbn} | pub={pub}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n=== TEST 5: Open Library search ===")
try:
    import requests
    resp = requests.get(
        "https://openlibrary.org/search.json",
        params={"q": KEYWORD, "publish_year": "2025", "limit": 10},
        timeout=15
    )
    print(f"  OpenLibrary status: {resp.status_code}")
    data = resp.json()
    docs = data.get("docs", [])
    print(f"  Docs returned: {len(docs)}")
    for doc in docs[:5]:
        isbn = (doc.get("isbn") or [""])[0]
        pub = doc.get("first_publish_year","?")
        print(f"    {doc.get('title','?')[:50]} | isbn={isbn} | pub={pub}")
except Exception as e:
    print(f"  ERROR: {e}")
