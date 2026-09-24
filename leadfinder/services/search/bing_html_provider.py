"""
Bing HTML Search Provider — free, no API key. Scrapes Bing web results
with requests + BeautifulSoup as an extra search layer.
"""
from __future__ import annotations

import logging
import time

import requests
from bs4 import BeautifulSoup
from django.conf import settings

from .base import SearchProvider, SearchResultDTO

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class BingHTMLSearchProvider(SearchProvider):
    """Free Bing HTML scrape — no API key required."""

    provider_name = "bing_html"

    def __init__(self, delay: float | None = None) -> None:
        self.delay = float(
            delay
            if delay is not None
            else getattr(
                settings,
                "APP_SEARCH_DELAY_SECONDS",
                getattr(settings, "APP_REQUEST_DELAY_SECONDS", 0.4),
            )
        )
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def search(self, query: str, max_results: int = 10) -> list[SearchResultDTO]:
        time.sleep(self.delay)
        resp = self._session.get(
            "https://www.bing.com/search",
            params={"q": query, "count": max_results, "setlang": "en-us"},
            timeout=int(getattr(settings, "APP_REQUEST_TIMEOUT_SECONDS", 15)),
        )
        resp.raise_for_status()
        return self._parse(resp.text, max_results)

    def _parse(self, html: str, max_results: int) -> list[SearchResultDTO]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[SearchResultDTO] = []
        rank = 1

        for item in soup.select("li.b_algo"):
            if len(results) >= max_results:
                break
            a = item.select_one("h2 a")
            if not a:
                continue
            url = (a.get("href") or "").strip()
            if not url.startswith("http"):
                continue
            title = a.get_text(strip=True)
            snippet_el = item.select_one(".b_caption p")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            results.append(
                SearchResultDTO(
                    title=title,
                    url=url,
                    snippet=snippet,
                    rank=rank,
                    provider=self.provider_name,
                )
            )
            rank += 1

        return results
