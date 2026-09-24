from __future__ import annotations

import os

from .base import SearchProvider
from .bing_html_provider import BingHTMLSearchProvider
from .brave_provider import BraveSearchProvider
from .cache import CachedSearchProvider
from .ddgs_html_provider import DDGHTMLSearchProvider
from .ddgs_provider import DDGSSearchProvider
from .fallback_provider import FallbackSearchProvider
from .tavily_provider import TavilySearchProvider
from .google_provider import GoogleSearchProvider


def get_search_provider(name: str | None = None) -> SearchProvider:
    selected = (name or os.getenv("SEARCH_PROVIDER") or "ddgs").lower()
    if selected == "tavily" and os.getenv("TAVILY_API_KEY"):
        return CachedSearchProvider(TavilySearchProvider())
    if selected == "brave" and os.getenv("BRAVE_API_KEY"):
        return CachedSearchProvider(BraveSearchProvider())
    if selected == "google" and os.getenv("GOOGLE_API_KEY") and os.getenv("GOOGLE_CSE_ID"):
        return CachedSearchProvider(GoogleSearchProvider())
    if selected == "ddgs_html":
        return CachedSearchProvider(DDGHTMLSearchProvider())
    if selected == "bing_html":
        return CachedSearchProvider(BingHTMLSearchProvider())
    if selected in {"fallback", "multi", "auto"}:
        return CachedSearchProvider(FallbackSearchProvider())
    return CachedSearchProvider(DDGSSearchProvider())
