from __future__ import annotations

import os
import pytest
from leadfinder.services.search.tavily_provider import TavilySearchProvider
from leadfinder.services.search.base import SearchResultDTO

class FakeTavilyClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.last_query = ""
        self.last_max_results = 10
        self.last_search_depth = "advanced"

    def search(self, query, max_results=10, search_depth="advanced"):
        self.last_query = query
        self.last_max_results = max_results
        self.last_search_depth = search_depth
        return {
            "results": [
                {
                    "title": "Tavily mock book",
                    "url": "https://amazon.com/dp/1234567890",
                    "content": "A beautiful story book for kids.",
                }
            ]
        }

def test_tavily_search_provider_query_cleaning(monkeypatch):
    fake_client_instance = None

    def mock_tavily_client(api_key):
        nonlocal fake_client_instance
        fake_client_instance = FakeTavilyClient(api_key)
        return fake_client_instance

    # Ensure tavily import doesn't fail if not installed in env
    import sys
    from types import ModuleType
    mock_tavily_module = ModuleType("tavily")
    mock_tavily_module.TavilyClient = mock_tavily_client
    sys.modules["tavily"] = mock_tavily_module

    provider = TavilySearchProvider(api_key="fake-tavily-key")
    
    # Test normalization of site: and quotes
    results = provider.search('site:amazon.com/dp "children picture book"', max_results=5)
    
    assert fake_client_instance is not None
    assert fake_client_instance.last_query == "amazon.com children picture book"
    assert fake_client_instance.last_max_results == 5
    assert len(results) == 1
    assert results[0].title == "Tavily mock book"
    assert results[0].url == "https://amazon.com/dp/1234567890"

def test_tavily_search_provider_fallback(monkeypatch):
    ddgs_called = False

    class MockDDGSSearchProvider:
        def search(self, query, max_results=10):
            nonlocal ddgs_called
            ddgs_called = True
            return [
                SearchResultDTO(
                    title="DDGS fallback result",
                    url="https://fallback.com",
                    snippet="ddgs snippet",
                    rank=1,
                    provider="ddgs"
                )
            ]

    monkeypatch.setattr(
        "leadfinder.services.search.ddgs_provider.DDGSSearchProvider",
        MockDDGSSearchProvider
    )

    # Trigger fallback when exception is raised by client search
    def mock_tavily_client_error(api_key):
        class BadClient:
            def search(self, *args, **kwargs):
                raise RuntimeError("API quota exceeded")
        return BadClient()

    import sys
    from types import ModuleType
    mock_tavily_module = ModuleType("tavily")
    mock_tavily_module.TavilyClient = mock_tavily_client_error
    sys.modules["tavily"] = mock_tavily_module

    provider = TavilySearchProvider(api_key="fake-tavily-key")
    results = provider.search("some query")

    assert ddgs_called is True
    assert len(results) == 1
    assert results[0].title == "DDGS fallback result"
