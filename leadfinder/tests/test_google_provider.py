from __future__ import annotations

import httpx
import pytest

from leadfinder.services.search.google_provider import GoogleSearchProvider
from leadfinder.services.search.base import SearchResultDTO


class FakeHttpxResponse:
    def __init__(self, json_data, status_code=200):
        self.json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                message=f"{self.status_code} Error",
                request=httpx.Request("GET", "https://www.googleapis.com/customsearch/v1"),
                response=httpx.Response(self.status_code),
            )

    def json(self):
        return self.json_data


def test_google_search_provider_success(monkeypatch):
    payload = {
        "items": [
            {
                "title": "Author Jane Doe | Children's Books",
                "link": "https://janedoe.com",
                "snippet": "Official website of Jane Doe, author of award-winning picture books.",
            },
            {
                "title": "Jane Doe (@janedoe) • Instagram photos and videos",
                "link": "https://instagram.com/janedoe",
                "snippet": "Jane Doe's official instagram account.",
            }
        ]
    }

    monkeypatch.setattr(
        "leadfinder.services.search.google_provider.httpx.get",
        lambda *args, **kwargs: FakeHttpxResponse(payload)
    )

    provider = GoogleSearchProvider(api_key="fake-key", cse_id="fake-cx")
    results = provider.search("Jane Doe children's author", max_results=5)

    assert len(results) == 2
    assert results[0].title == "Author Jane Doe | Children's Books"
    assert results[0].url == "https://janedoe.com"
    assert results[0].snippet == "Official website of Jane Doe, author of award-winning picture books."
    assert results[0].rank == 1
    assert results[0].provider == "google"

    assert results[1].title == "Jane Doe (@janedoe) • Instagram photos and videos"
    assert results[1].url == "https://instagram.com/janedoe"
    assert results[1].rank == 2
    assert results[1].provider == "google"


def test_google_search_provider_missing_keys_fallback(monkeypatch):
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

    # Missing API key or CSE ID
    provider = GoogleSearchProvider(api_key="", cse_id="")
    results = provider.search("Jane Doe", max_results=2)

    assert ddgs_called is True
    assert len(results) == 1
    assert results[0].title == "DDGS fallback result"
    assert results[0].provider == "ddgs"


def test_google_search_provider_quota_error_fallback(monkeypatch):
    ddgs_called = False

    class MockDDGSSearchProvider:
        def search(self, query, max_results=10):
            nonlocal ddgs_called
            ddgs_called = True
            return [
                SearchResultDTO(
                    title="DDGS fallback result after quota error",
                    url="https://fallback-quota.com",
                    snippet="ddgs snippet quota",
                    rank=1,
                    provider="ddgs"
                )
            ]

    monkeypatch.setattr(
        "leadfinder.services.search.ddgs_provider.DDGSSearchProvider",
        MockDDGSSearchProvider
    )

    # Simulate HTTP 429 Limit Exceeded from Google API
    monkeypatch.setattr(
        "leadfinder.services.search.google_provider.httpx.get",
        lambda *args, **kwargs: FakeHttpxResponse({}, status_code=429)
    )

    provider = GoogleSearchProvider(api_key="fake-key", cse_id="fake-cx")
    results = provider.search("Jane Doe", max_results=2)

    assert ddgs_called is True
    assert len(results) == 1
    assert results[0].title == "DDGS fallback result after quota error"
    assert results[0].provider == "ddgs"
