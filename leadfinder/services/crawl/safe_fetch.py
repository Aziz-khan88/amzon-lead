from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from django.conf import settings

from leadfinder.utils.url_safety import is_safe_public_url

from ..parallel import HostRateLimiter
from .proxies import proxies_for_url
from .robots import can_fetch_url, crawl_delay_for


USER_AGENT = "BookTrailerLeadFinder/1.0 (+public lead research; respects robots.txt)"
MAX_CRAWL_BYTES = 2_000_000
MAX_CRAWL_REDIRECTS = 3

# Parallel stages may fetch several hosts at once, but requests to the SAME
# host always serialize behind this limiter so crawling stays polite.
_HOST_RATE_LIMITER = HostRateLimiter()


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
    """Fetch a bounded, robots-permitted author page with safe redirect hops.

    Concurrent callers fetching DIFFERENT hosts run in parallel; callers
    hitting the SAME host serialize behind a per-host lock so the crawl delay
    paces consecutive hits instead of parallel bursts.
    """

    timeout = int(getattr(settings, "APP_REQUEST_TIMEOUT_SECONDS", 15))
    current_url = url
    response = None
    host_lock = _HOST_RATE_LIMITER.lock_for((urlparse(url).hostname or "").lower())
    with host_lock:
        for _ in range(MAX_CRAWL_REDIRECTS + 1):
            if (
                not is_safe_public_url(current_url)
                or is_ignored_crawl_host(current_url)
                or not can_fetch_url(current_url, USER_AGENT)
            ):
                return None
            configured_delay = float(getattr(settings, "APP_CRAWL_DELAY_SECONDS", getattr(settings, "APP_REQUEST_DELAY_SECONDS", 0.4)))
            time.sleep(max(configured_delay, crawl_delay_for(current_url, USER_AGENT)))
            try:
                response = requests.get(
                    current_url,
                    headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
                    timeout=timeout,
                    allow_redirects=False,
                    stream=True,
                    proxies=proxies_for_url(current_url),
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
        "contact-us",
        "about",
        "about-me",
        "about-the-author",
        "author",
        "books",
        "media",
        "media-kit",
        "press",
        "press-kit",
        "school-visits",
        "author-visits",
        "speaking",
        "events",
        "appearances",
        "work-with-me",
        "hire-me",
        "faq",
    ]
    return [urljoin(root, path) for path in paths]


# URL path fragments and anchor text that signal a page likely carrying public
# contact details.  Used to discover contact pages the fixed path list misses
# (e.g. ``/visit-me``, ``/booking-info``, ``/get-in-touch``) by reading the
# links already present on crawled author pages — one bounded hop deeper.
CONTACT_LINK_PATH_RE = re.compile(
    r"(contact|about|media|press|booking|visit|speak|appear|event|hire|work-with|"
    r"get-in-touch|reach|email|agent|represent|publicit|school|media-?kit|press-?kit|faq)",
    re.IGNORECASE,
)

MAX_DISCOVERED_CONTACT_LINKS = 12


def discover_contact_links(html: str, page_url: str, *, limit: int | None = None) -> list[str]:
    """Find same-domain, contact-intent links on an already-fetched page.

    This powers the second crawl hop: the fixed ``candidate_author_pages``
    paths cover common layouts, but self-hosted author sites hide contact
    details behind custom slugs.  Only same-host links are returned so the
    crawl never wanders off the identity-trusted author domain.  Links
    pointing at files (pdf/jpg/zip/...) are skipped.
    """

    if not html or not page_url:
        return []
    parsed_page = urlparse(page_url)
    host = (parsed_page.hostname or "").lower()
    if not host:
        return []
    cap = max(1, min(int(limit or MAX_DISCOVERED_CONTACT_LINKS), 25))
    soup = BeautifulSoup(html, "lxml")
    discovered: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = urljoin(page_url, str(tag["href"]).split("#", 1)[0].strip())
        parsed = urlparse(href)
        if parsed.scheme not in {"http", "https"}:
            continue
        link_host = (parsed.hostname or "").lower()
        if link_host != host and not link_host.endswith(f".{host.lstrip('www.')}"):
            continue
        path = (parsed.path or "/").strip("/")
        if not path:  # homepage — already in the fixed path list
            continue
        if re.search(r"\.(pdf|jpe?g|png|gif|zip|docx?|xlsx?|mp3|mp4|svg|webp|css|js)$", path, re.I):
            continue
        anchor_text = tag.get_text(" ", strip=True)[:120]
        if not (CONTACT_LINK_PATH_RE.search(path) or CONTACT_LINK_PATH_RE.search(anchor_text)):
            continue
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if normalized.rstrip("/") == page_url.rstrip("/"):
            continue
        if normalized not in discovered:
            discovered.append(normalized)
        if len(discovered) >= cap:
            break
    return discovered
