from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from django.conf import settings

from leadfinder.utils.url_safety import is_safe_public_url

from .robots import can_fetch_url


USER_AGENT = "BookTrailerLeadFinder/1.0 (+public lead research; respects robots.txt)"
MAX_CRAWL_BYTES = 2_000_000
MAX_CRAWL_REDIRECTS = 3


@dataclass(slots=True)
class FetchedPage:
    url: str
    status_code: int
    html: str
    content_type: str


def is_ignored_crawl_host(url: str) -> bool:
    """Checks if a URL belongs to catalog directories, retailers, or academic portals to ignore crawling them."""
    if not url:
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    
    # Do not ignore booklife.com as safe_fetch is used by the booklife scraper to fetch details
    if "booklife.com" in host:
        return False
        
    ignored_parts = {
        "amazon.", "goodreads.", "openlibrary.", "archive.org", "librarything.",
        "worldcat.", "loc.gov", "wikipedia.", "wikidata.", "facebook.com",
        "instagram.com", "youtube.com", "youtu.be", "linkedin.com", "twitter.com",
        "x.com", "pinterest.com", "tiktok.com", "ebay.com", "etsy.com", "target.com",
        "walmart.com", "mitpressbookstore.", "mit.edu", "harvard.edu", "yale.edu",
        "stanford.edu", "scholastic.com", "penguinrandomhouse.com", "harpercollins.com",
        "simonandschuster.com", "macmillan.com", "hachettebookgroup.com", "bloomsbury.com",
        "fantasticfiction.com", "fantasticfiction.co.uk", "bookbub.com", "litcharts.com",
        "sparknotes.com"
    }
    return any(part in host for part in ignored_parts)


def safe_fetch(url: str) -> FetchedPage | None:
    """Fetch a bounded, robots-permitted author page with safe redirect hops."""

    timeout = int(getattr(settings, "APP_REQUEST_TIMEOUT_SECONDS", 15))
    current_url = url
    response = None
    for _ in range(MAX_CRAWL_REDIRECTS + 1):
        if (
            not is_safe_public_url(current_url)
            or is_ignored_crawl_host(current_url)
            or not can_fetch_url(current_url, USER_AGENT)
        ):
            return None
        time.sleep(float(getattr(settings, "APP_CRAWL_DELAY_SECONDS", getattr(settings, "APP_REQUEST_DELAY_SECONDS", 0.4))))
        try:
            response = requests.get(
                current_url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
                timeout=timeout,
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException:
            return None
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("location")
            response.close()
            if not location:
                return None
            current_url = urljoin(current_url, location)
            continue
        break
    else:
        return None

    if response is None or response.status_code >= 400:
        if response is not None:
            response.close()
        return None
    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        response.close()
        return None
    body = bytearray()
    try:
        for chunk in response.iter_content(chunk_size=65_536):
            body.extend(chunk)
            if len(body) > MAX_CRAWL_BYTES:
                return None
    finally:
        response.close()
    return FetchedPage(
        url=current_url,
        status_code=response.status_code,
        html=bytes(body).decode(response.encoding or "utf-8", errors="replace"),
        content_type=content_type,
    )


def candidate_author_pages(base_url: str) -> list[str]:
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}/"
    paths = [
        "",
        "contact",
        "about",
        "about-me",
        "author",
        "books",
        "media",
        "press",
        "school-visits",
        "speaking",
        "events",
    ]
    return [urljoin(root, path) for path in paths]
