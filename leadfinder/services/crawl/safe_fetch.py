from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from django.conf import settings

from leadfinder.utils.url_safety import is_safe_public_url

from .robots import can_fetch_url


USER_AGENT = "BookTrailerLeadFinder/1.0 (+public lead research; respects robots.txt)"


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
    if not is_safe_public_url(url):
        return None
    if is_ignored_crawl_host(url):
        return None
    if not can_fetch_url(url, USER_AGENT):
        return None
    timeout = int(getattr(settings, "APP_REQUEST_TIMEOUT_SECONDS", 15))
    time.sleep(float(getattr(settings, "APP_CRAWL_DELAY_SECONDS", getattr(settings, "APP_REQUEST_DELAY_SECONDS", 0.4))))
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None
    final_url = response.url
    if not is_safe_public_url(final_url):
        return None
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and "application/xhtml" not in content_type:
        return None
    return FetchedPage(
        url=final_url,
        status_code=response.status_code,
        html=response.text,
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
