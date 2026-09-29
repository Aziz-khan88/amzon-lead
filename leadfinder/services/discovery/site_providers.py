"""Specialized discovery sources built on top of the configured web-search provider.

Direct HTML scraping of Kickstarter, Goodreads, and Amazon listing pages is
fragile (JS rendering, bot walls), so these providers discover candidates
through search-engine result pages restricted to each site, then parse
title/author heuristics from the result titles and snippets.  Every candidate
carries its source URL/title/snippet so downstream evidence recording stays
auditable exactly like keyword discovery.

Registered providers
--------------------
- ``kickstarter``           — live Publishing > Children's Books crowdfunding
                              campaigns (authors actively spending on their book).
- ``goodreads_giveaways``   — authors currently running Goodreads giveaways
                              (actively marketing, high intent).
- ``scbwi``                 — SCBWI member/author pages (verified children's
                              authors by definition).
- ``amazon_new_releases``   — time-scoped Amazon new-release sweeps for
                              children's picture books.
"""

from __future__ import annotations

import re
from datetime import date

from leadfinder.services.amazon.amazon_url_parser import extract_asin, is_amazon_url, normalize_amazon_book_url


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _split_title_author(title: str, snippet: str) -> tuple[str, str]:
    """Best-effort 'Title by Author' parsing of a search-result title."""

    text = _clean(title)
    # Drop common site suffixes: "Moon Cat by L. Ray | Goodreads".
    text = re.sub(r"\s*[|]\s*[^|]{0,60}$", "", text)
    # End-anchored "by First Last" (1-4 capitalized words), allowing colons
    # and subtitles inside the title portion.
    match = re.search(
        r"^(?P<title>.{3,150}?)\s+by\s+(?P<author>[A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+){0,3})\s*$",
        text,
    )
    if match:
        return _clean(match.group("title")), _clean(match.group("author"))
    return text[:120], ""


class SiteDiscoveryProvider:
    """Search-index discovery restricted to one site, with per-site parsing."""

    def __init__(
        self,
        provider_name: str,
        host_fragment: str,
        query_templates: list[str],
        *,
        asin_only: bool = False,
        base_confidence: float = 0.45,
    ):
        self.provider_name = provider_name
        self.host_fragment = host_fragment
        self.query_templates = query_templates
        self.asin_only = asin_only
        self.base_confidence = base_confidence

    def queries(self, keyword: str) -> list[str]:
        year = date.today().year
        return [template.format(keyword=_clean(keyword) or "children's picture book", year=year) for template in self.query_templates]

    def discover(self, keyword: str, *, max_books: int, search_provider, max_results: int = 8, logger=None) -> tuple[list[dict], list[str]]:
        """Return (candidates, errors).  Never raises for search failures."""

        candidates: list[dict] = []
        errors: list[str] = []
        seen_keys: set[str] = set()
        for query in self.queries(keyword):
            try:
                results = search_provider.search(query, max_results=max_results)
            except Exception as exc:  # noqa: BLE001 - recorded, then next query
                errors.append(str(exc))
                continue
            for dto in results:
                url = getattr(dto, "url", "") or ""
                if self.host_fragment not in url.lower():
                    continue
                title, author = _split_title_author(getattr(dto, "title", ""), getattr(dto, "snippet", "") or "")
                if not title:
                    continue
                asin = (extract_asin(url) or "") if is_amazon_url(url) else ""
                if self.asin_only and not asin:
                    continue
                key = asin or f"{title.lower()}::{author.lower()}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                candidates.append(
                    {
                        "title": title,
                        "author_name": author,
                        "asin": asin,
                        "amazon_book_url": normalize_amazon_book_url(url, None) if asin else "",
                        "amazon_source_url": url,
                        "amazon_source_title": _clean(getattr(dto, "title", ""))[:500],
                        "amazon_source_snippet": _clean(getattr(dto, "snippet", "") or ""),
                        "book_data_confidence": self.base_confidence,
                        "source_provider": self.provider_name,
                        "source_raw_json": {"query": query, "discovery_source": self.provider_name},
                    }
                )
                if len(candidates) >= max_books:
                    return candidates, errors
        return candidates, errors


KICKSTARTER_PROVIDER = SiteDiscoveryProvider(
    provider_name="kickstarter",
    host_fragment="kickstarter.com",
    query_templates=[
        'site:kickstarter.com/projects children\'s picture book {year}',
        "site:kickstarter.com/projects \"picture book\" {keyword}",
        "site:kickstarter.com/projects kids book illustration by",
    ],
    base_confidence=0.5,
)

GOODREADS_GIVEAWAY_PROVIDER = SiteDiscoveryProvider(
    provider_name="goodreads_giveaways",
    host_fragment="goodreads.com",
    query_templates=[
        "site:goodreads.com/giveaway children's picture book",
        "site:goodreads.com/giveaway \"picture book\" {year}",
        "site:goodreads.com/giveaway {keyword}",
    ],
    base_confidence=0.45,
)

SCBWI_PROVIDER = SiteDiscoveryProvider(
    provider_name="scbwi",
    host_fragment="scbwi.org",
    query_templates=[
        "site:scbwi.org member picture book author",
        "site:scbwi.org {keyword} author illustrator",
        'site:scbwi.org "picture book" author profile',
    ],
    base_confidence=0.5,
)

AMAZON_NEW_RELEASES_PROVIDER = SiteDiscoveryProvider(
    provider_name="amazon_new_releases",
    host_fragment="amazon.",
    query_templates=[
        "site:amazon.com children's picture book new release {year}",
        "site:amazon.com \"picture book\" \"new release\" {keyword}",
        "site:amazon.com kids picture book published {year} by",
    ],
    asin_only=True,
    base_confidence=0.5,
)

SITE_DISCOVERY_PROVIDERS = {
    provider.provider_name: provider
    for provider in (KICKSTARTER_PROVIDER, GOODREADS_GIVEAWAY_PROVIDER, SCBWI_PROVIDER, AMAZON_NEW_RELEASES_PROVIDER)
}
