from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SearchResultDTO:
    title: str
    url: str
    snippet: str | None
    rank: int
    provider: str


class SearchProvider:
    provider_name = "base"

    def search(self, query: str, max_results: int = 10) -> list[SearchResultDTO]:
        raise NotImplementedError
