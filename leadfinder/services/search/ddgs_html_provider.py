"""
DDG HTML Search Provider — uses requests + BeautifulSoup to scrape
DuckDuckGo HTML results. No external library dependency required.
"""
from __future__ import annotations

import logging
import re
import time
import urllib.parse

import requests
from bs4 import BeautifulSoup

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

# DuckDuckGo redirect prefix
_DDG_REDIRECT_RE = re.compile(r"uddg=([^&]+)", re.I)


def _decode_ddg_url(href: str) -> str:
    """Decode DuckDuckGo redirect URLs like //duckduckgo.com/l/?uddg=..."""
    m = _DDG_REDIRECT_RE.search(href)
    if m:
        return urllib.parse.unquote(m.group(1))
    if href.startswith("//"):
        href = "https:" + href
    return href


class DDGHTMLSearchProvider(SearchProvider):
    """
    Scrapes DuckDuckGo HTML endpoint — reliable fallback when ddgs package
    is not installed or rate-limited.
    """
    provider_name = "ddgs_html"

    def __init__(self, delay: float = 0.5) -> None:
        self.delay = delay
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def search(self, query: str, max_results: int = 10) -> list[SearchResultDTO]:
        time.sleep(self.delay)
        results: list[SearchResultDTO] = []

        # Try HTML endpoint (POST)
        try:
            results = self._search_html_post(query, max_results)
        except Exception as e:
            logger.warning("DDG HTML POST failed: %s", e)

        # Fallback: try Lite endpoint (GET)
        if not results:
            try:
                results = self._search_lite_get(query, max_results)
            except Exception as e:
                logger.warning("DDG Lite GET failed: %s", e)

        return results[:max_results]

    def _search_html_post(self, query: str, max_results: int) -> list[SearchResultDTO]:
        resp = self._session.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "b": "", "kl": "us-en"},
            timeout=20,
        )
        resp.raise_for_status()
        return self._parse_html(resp.text, max_results)

    def _search_lite_get(self, query: str, max_results: int) -> list[SearchResultDTO]:
        resp = self._session.get(
            "https://lite.duckduckgo.com/lite/",
            params={"q": query, "kl": "us-en"},
            timeout=20,
        )
        resp.raise_for_status()
        return self._parse_lite(resp.text, max_results)

    def _parse_html(self, html: str, max_results: int) -> list[SearchResultDTO]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[SearchResultDTO] = []
        rank = 1

        for result_div in soup.select(".result"):
            if len(results) >= max_results:
                break
            a = result_div.select_one(".result__a, a.result__url")
            snippet_el = result_div.select_one(".result__snippet")

            if not a:
                continue

            title = a.get_text(strip=True)
            href = a.get("href", "")
            url = _decode_ddg_url(href) if href else ""
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            if url:
                results.append(SearchResultDTO(
                    title=title,
                    url=url,
                    snippet=snippet,
                    rank=rank,
                    provider=self.provider_name,
                ))
                rank += 1

        return results

    def _parse_lite(self, html: str, max_results: int) -> list[SearchResultDTO]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[SearchResultDTO] = []
        rank = 1

        for a in soup.select("td a.result-link, td a"):
            if len(results) >= max_results:
                break
            href = a.get("href", "")
            url = _decode_ddg_url(href)
            title = a.get_text(strip=True)
            if url and url.startswith("http"):
                results.append(SearchResultDTO(
                    title=title,
                    url=url,
                    snippet="",
                    rank=rank,
                    provider=self.provider_name,
                ))
                rank += 1

        return results
