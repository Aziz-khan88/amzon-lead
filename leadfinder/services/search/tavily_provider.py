from __future__ import annotations

import logging
import os

from .base import SearchProvider, SearchResultDTO

logger = logging.getLogger(__name__)


class TavilySearchProvider(SearchProvider):
    provider_name = "tavily"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("TAVILY_API_KEY", "")

    def _clean_query(self, query: str) -> str:
        # Strip site: operator and keep the domain
        cleaned = query.replace("site:amazon.com/dp", "amazon.com")
        cleaned = cleaned.replace("site:amazon.com", "amazon.com")
        cleaned = cleaned.replace("site:books.google.com", "books.google.com")
        
        # Remove any other site: operators if they exist
        import re
        cleaned = re.sub(r"site:(\S+)", r"\1", cleaned)
        
        # Strip quotes
        cleaned = cleaned.replace('"', '').replace("'", "")
        
        # Normalize whitespace
        cleaned = " ".join(cleaned.split())
        return cleaned

    def search(self, query: str, max_results: int = 10) -> list[SearchResultDTO]:
        if not self.api_key:
            from .ddgs_provider import DDGSSearchProvider
            return DDGSSearchProvider().search(query, max_results)
        try:
            from tavily import TavilyClient
        except Exception:
            from .ddgs_provider import DDGSSearchProvider
            return DDGSSearchProvider().search(query, max_results)
        try:
            cleaned_query = self._clean_query(query)
            logger.info(f"Tavily original query: '{query}', cleaned to: '{cleaned_query}'")
            response = TavilyClient(api_key=self.api_key).search(
                query=cleaned_query,
                max_results=max_results,
                search_depth=os.getenv("TAVILY_SEARCH_DEPTH", "advanced"),
            )
            results = []
            for rank, item in enumerate(response.get("results", [])[:max_results], start=1):
                results.append(
                    SearchResultDTO(
                        title=item.get("title") or "",
                        url=item.get("url") or "",
                        snippet=item.get("content") or "",
                        rank=rank,
                        provider=self.provider_name,
                    )
                )
            res = [result for result in results if result.url]
            if res:
                return res
        except Exception as exc:
            logger.warning(f"Tavily search failed, falling back to DuckDuckGo: {exc}")
        
        # Fallback if Tavily raises rate limit/quota or other exception
        from .ddgs_provider import DDGSSearchProvider
        return DDGSSearchProvider().search(query, max_results)
