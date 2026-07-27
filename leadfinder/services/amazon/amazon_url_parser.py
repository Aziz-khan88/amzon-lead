from __future__ import annotations

import re
from urllib.parse import urlencode, urlparse, urlunparse


# Amazon's supported retail marketplaces. Keeping this explicit prevents hosts
# such as ``amazon.com.example.org`` from being treated as Amazon evidence.
AMAZON_MARKETPLACE_HOSTS = frozenset(
    {
        "amazon.com",
        "amazon.ca",
        "amazon.com.mx",
        "amazon.com.br",
        "amazon.co.uk",
        "amazon.de",
        "amazon.fr",
        "amazon.it",
        "amazon.es",
        "amazon.nl",
        "amazon.se",
        "amazon.pl",
        "amazon.com.be",
        "amazon.in",
        "amazon.co.jp",
        "amazon.com.au",
        "amazon.sg",
        "amazon.ae",
        "amazon.sa",
        "amazon.com.tr",
        "amazon.eg",
    }
)
ASIN_RE = re.compile(r"/(?:dp|gp/product|product)/([A-Z0-9]{10})(?:[/?#]|$)", re.I)


def amazon_marketplace_host(url: str) -> str | None:
    """Return the canonical marketplace host for a genuine Amazon URL."""
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except (TypeError, ValueError):
        return None
    for marketplace in AMAZON_MARKETPLACE_HOSTS:
        if host == marketplace or host.endswith(f".{marketplace}"):
            return marketplace
    return None


def is_amazon_url(url: str) -> bool:
    return amazon_marketplace_host(url) is not None


def extract_asin(url: str) -> str | None:
    match = ASIN_RE.search(url)
    if not match:
        return None
    return match.group(1).upper()


def normalize_amazon_book_url(url: str, associate_tag: str | None = None) -> str:
    marketplace = amazon_marketplace_host(url)
    if not marketplace:
        return url
    asin = extract_asin(url)
    if not asin:
        return url
    query = urlencode({"tag": associate_tag}) if associate_tag else ""
    return urlunparse(("https", f"www.{marketplace}", f"/dp/{asin}", "", query, ""))


def classify_amazon_search_result(title: str, url: str, snippet: str | None = None) -> float:
    if not is_amazon_url(url):
        return 0.0
    confidence = 0.45
    if extract_asin(url):
        confidence += 0.35
    text = f"{title} {snippet or ''}".lower()
    if any(term in text for term in ["children", "kids", "picture book", "paperback", "book"]):
        confidence += 0.15
    return min(confidence, 0.95)
