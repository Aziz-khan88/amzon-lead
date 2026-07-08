from __future__ import annotations

import re
from urllib.parse import urlencode, urlparse, urlunparse


AMAZON_HOST_RE = re.compile(r"(^|\.)amazon\.[a-z.]+$", re.I)
ASIN_RE = re.compile(r"/(?:dp|gp/product|product)/([A-Z0-9]{10})(?:[/?#]|$)", re.I)


def is_amazon_url(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    return bool(AMAZON_HOST_RE.search(host))


def extract_asin(url: str) -> str | None:
    match = ASIN_RE.search(url)
    if not match:
        return None
    return match.group(1).upper()


def normalize_amazon_book_url(url: str, associate_tag: str | None = None) -> str:
    asin = extract_asin(url)
    if not asin:
        return url
    query = urlencode({"tag": associate_tag}) if associate_tag else ""
    return urlunparse(("https", "www.amazon.com", f"/dp/{asin}", "", query, ""))


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
