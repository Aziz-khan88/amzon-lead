"""
Fallback Search Provider — chains multiple free search providers.  The first
non-empty result set wins, but THIN sets (fewer hits than the caller asked
for) are augmented from the next provider in the chain, so a weak engine
never caps recall on its own.  Adds resilience when one engine rate-limits
or returns nothing.
"""
from __future__ import annotations

import logging

from django.conf import settings

import os

from .base import SearchProvider, SearchResultDTO
from .bing_html_provider import BingHTMLSearchProvider
from .ddgs_html_provider import DDGHTMLSearchProvider
from .ddgs_provider import DDGSSearchProvider
from .google_provider import GoogleSearchProvider
from .tavily_provider import TavilySearchProvider

logger = logging.getLogger(__name__)

# Registry of providers that can participate in the fallback chain.
_FREE_PROVIDER_REGISTRY: dict[str, type[SearchProvider]] = {
    "google": GoogleSearchProvider,
    "tavily": TavilySearchProvider,
    "ddgs": DDGSSearchProvider,
    "ddgs_html": DDGHTMLSearchProvider,
    "bing_html": BingHTMLSearchProvider,
}

def _default_chain() -> list[str]:
    chain = []
    if os.getenv("GOOGLE_API_KEY") and os.getenv("GOOGLE_CSE_ID"):
        chain.append("google")
    if os.getenv("TAVILY_API_KEY"):
        chain.append("tavily")
    chain.extend(["ddgs", "ddgs_html", "bing_html"])
    return chain

DEFAULT_CHAIN = "ddgs,ddgs_html,bing_html"



def _normalized_url_key(url: str) -> str:
    """Dedupe key: scheme/tracking-insensitive host+path identity."""

    return (url or "").lower().replace("https://", "").replace("http://", "").split("?")[0].split("#")[0].rstrip("/")


def _merge_results(
    base: list[SearchResultDTO],
    extra: list[SearchResultDTO],
    max_results: int,
) -> list[SearchResultDTO]:
    """Append unseen URLs from ``extra`` onto ``base``, re-ranking densely."""

    seen = {_normalized_url_key(result.url) for result in base}
    merged = list(base)
    for result in extra:
        key = _normalized_url_key(result.url)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(result)
        if len(merged) >= max_results:
            break
    return [
        SearchResultDTO(title=r.title, url=r.url, snippet=r.snippet, rank=index, provider=r.provider)
        for index, r in enumerate(merged[:max_results], start=1)
    ]


class FallbackSearchProvider(SearchProvider):
    """
    Tries each configured free provider in order until one returns results.

    When the first provider that answers returns a thin set (fewer hits than
    requested), later providers top it up; results are URL-deduped and
    re-ranked.  Total provider calls stay bounded by the chain length and the
    chain short-circuits as soon as the set is full.

    Configure the chain with the SEARCH_FALLBACK_PROVIDERS env var, e.g.:
        SEARCH_FALLBACK_PROVIDERS=ddgs,bing_html,ddgs_html
    """

    provider_name = "fallback"

    def __init__(self, chain: list[str] | None = None) -> None:
        if chain is None:
            raw = getattr(settings, "SEARCH_FALLBACK_PROVIDERS", None)
            if raw:
                chain = [name.strip() for name in str(raw).split(",") if name.strip()]
            else:
                chain = _default_chain()

        self._providers: list[SearchProvider] = [
            _FREE_PROVIDER_REGISTRY[name]()
            for name in chain
            if name in _FREE_PROVIDER_REGISTRY
        ]
        if not self._providers:
            self._providers = [DDGSSearchProvider()]

    def search(self, query: str, max_results: int = 10) -> list[SearchResultDTO]:
        errors: list[str] = []
        merged: list[SearchResultDTO] = []
        for provider in self._providers:
            try:
                results = provider.search(query, max_results=max_results)
            except Exception as exc:
                errors.append(f"{provider.provider_name}: {exc}")
                logger.warning("Fallback layer %s failed: %s", provider.provider_name, exc)
                continue
            if not results:
                continue
            merged = _merge_results(merged, results, max_results)
            if len(merged) >= max_results:
                return merged
        if merged:
            return merged
        if errors:
            raise RuntimeError("All fallback search layers failed: " + " | ".join(errors[:3]))
        return []
