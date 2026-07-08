from __future__ import annotations

import os

import httpx

from .base import SearchProvider, SearchResultDTO


class BraveSearchProvider(SearchProvider):
    provider_name = "brave"
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("BRAVE_API_KEY", "")

    def search(self, query: str, max_results: int = 10) -> list[SearchResultDTO]:
        if not self.api_key:
            from .ddgs_provider import DDGSSearchProvider
            return DDGSSearchProvider().search(query, max_results)
        headers = {"Accept": "application/json", "X-Subscription-Token": self.api_key}
        try:
            response = httpx.get(
                self.endpoint,
                params={"q": query, "count": max_results},
                headers=headers,
                timeout=15,
            )
            response.raise_for_status()
            raw_results = response.json().get("web", {}).get("results", [])
            results = []
            for rank, item in enumerate(raw_results[:max_results], start=1):
                results.append(
                    SearchResultDTO(
                        title=item.get("title") or "",
                        url=item.get("url") or "",
                        snippet=item.get("description") or "",
                        rank=rank,
                        provider=self.provider_name,
                    )
                )
            res = [result for result in results if result.url]
            if res:
                return res
        except Exception:
            pass
            
        # Fallback to DuckDuckGo search if Brave fails or raises exception
        from .ddgs_provider import DDGSSearchProvider
        return DDGSSearchProvider().search(query, max_results)
