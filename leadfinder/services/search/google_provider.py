from __future__ import annotations

import os
import httpx

from .base import SearchProvider, SearchResultDTO


class GoogleSearchProvider(SearchProvider):
    provider_name = "google"
    endpoint = "https://www.googleapis.com/customsearch/v1"

    def __init__(self, api_key: str | None = None, cse_id: str | None = None) -> None:
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY", "")
        self.cse_id = cse_id or os.getenv("GOOGLE_CSE_ID", "")

    def search(self, query: str, max_results: int = 10) -> list[SearchResultDTO]:
        if not self.api_key or not self.cse_id:
            from .ddgs_provider import DDGSSearchProvider
            return DDGSSearchProvider().search(query, max_results)

        # The max result count per request in Custom Search JSON API is 10
        num = min(max(1, max_results), 10)
        params = {
            "q": query,
            "key": self.api_key,
            "cx": self.cse_id,
            "num": num,
        }
        try:
            response = httpx.get(
                self.endpoint,
                params=params,
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            raw_results = data.get("items", [])
            results = []
            for rank, item in enumerate(raw_results, start=1):
                url = item.get("link") or ""
                if not url:
                    continue
                results.append(
                    SearchResultDTO(
                        title=item.get("title") or "",
                        url=url,
                        snippet=item.get("snippet") or "",
                        rank=rank,
                        provider=self.provider_name,
                    )
                )
            if results:
                return results
        except Exception:
            pass

        # Fallback to DDGSSearchProvider if Google API fails or throws quota/network exception
        from .ddgs_provider import DDGSSearchProvider
        return DDGSSearchProvider().search(query, max_results)
