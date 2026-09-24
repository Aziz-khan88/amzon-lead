"""Tests for the improved search-query planning layer.

Covers:
- Scout discovery query diversification (round-robin across keyword variants).
- Harvester balanced author-query selection (site/contact/social coverage).
- Fallback provider merge-augmentation of thin result sets.
"""

from types import SimpleNamespace

from leadfinder.services.pipeline.process_book import (
    _title_anchor,
    author_discovery_queries,
    deep_contact_discovery_queries,
    select_author_discovery_queries,
)
from leadfinder.services.pipeline.run_research import discovery_queries
from leadfinder.services.search import fallback_provider
from leadfinder.services.search.base import SearchResultDTO
from leadfinder.services.search.fallback_provider import FallbackSearchProvider


def _book(author="Jane Doe", title="The Brave Little Fox"):
    return SimpleNamespace(author_name=author, title=title)


# --- Scout diversification -------------------------------------------------


def test_discovery_queries_diversify_across_variants():
    queries = discovery_queries("Children books")
    # First query stays the highest-yield pattern for the first variant.
    assert queries[0] == "amazon.com/dp children picture book by"
    # The early budget covers multiple variants, not multiple patterns of one.
    assert "amazon.com/dp kids picture book by" in queries[:6]
    assert any("new children picture book author" in query for query in queries[:8])


def test_discovery_queries_single_variant_order_unchanged():
    queries = discovery_queries("children of time")
    assert queries == [
        'site:amazon.com "children of time"',
        'amazon "children of time"',
        '"children of time" "amazon.com/dp"',
        "children of time",
    ]


# --- Title anchor ----------------------------------------------------------


def test_title_anchor_keeps_short_titles():
    assert _title_anchor("The Brave Little Fox") == "The Brave Little Fox"


def test_title_anchor_collapses_long_titles_to_significant_tokens():
    title = "The Amazing Adventures of a Very Brave Little Fox in the Great Big Forest"
    anchor = _title_anchor(title)
    assert len(anchor.split()) <= 4
    assert "Amazing" in anchor
    # Stopwords are dropped from the anchor.
    assert " the " not in f" {anchor.lower()} "


# --- Harvester balanced selection ------------------------------------------


def test_select_author_discovery_queries_balances_categories():
    queries = select_author_discovery_queries(_book(), 6)
    assert len(queries) == 6
    joined = " ".join(queries)
    # Site, contact, and social coverage all inside the small budget.
    assert "author website" in joined
    assert "contact" in joined
    assert "site:instagram.com" in joined or "site:facebook.com" in joined
    # Social site: queries must be reachable within the default budget now.
    default_budget = select_author_discovery_queries(_book(), 8)
    assert any(query.startswith("site:") for query in default_budget)


def test_select_author_discovery_queries_respects_limit_and_dedupes():
    queries = select_author_discovery_queries(_book(), 3)
    assert len(queries) == 3
    assert len(set(queries)) == 3


def test_author_queries_empty_without_author():
    assert select_author_discovery_queries(_book(author=""), 5) == []
    assert author_discovery_queries(_book(author="")) == []
    assert deep_contact_discovery_queries(_book(author="")) == []


def test_deep_contact_queries_use_anchor_for_long_titles():
    long_title = "The Amazing Adventures of a Very Brave Little Fox in the Great Big Forest"
    queries = deep_contact_discovery_queries(_book(title=long_title))
    assert queries
    # No query should embed the entire long title verbatim.
    assert all(long_title not in query for query in queries)


# --- Fallback provider merge-augmentation ----------------------------------


class _StubProvider:
    def __init__(self, name, results=None, error=None):
        self.provider_name = name
        self._results = results or []
        self._error = error
        self.calls = 0

    def search(self, query, max_results=10):
        self.calls += 1
        if self._error:
            raise RuntimeError(self._error)
        return [
            SearchResultDTO(title=f"{self.provider_name}-{i}", url=url, snippet="", rank=i + 1, provider=self.provider_name)
            for i, url in enumerate(self._results)
        ]


def _fallback_with(stubs):
    provider = FallbackSearchProvider(chain=[])
    provider._providers = stubs
    return provider


def test_fallback_returns_full_first_set_without_extra_calls():
    first = _StubProvider("a", results=[f"https://a{i}.com" for i in range(5)])
    second = _StubProvider("b", results=[f"https://b{i}.com" for i in range(5)])
    results = _fallback_with([first, second]).search("q", max_results=5)
    assert len(results) == 5
    assert second.calls == 0


def test_fallback_augments_thin_results_from_next_provider():
    first = _StubProvider("a", results=["https://a1.com", "https://a2.com"])
    second = _StubProvider("b", results=["https://b1.com", "https://a2.com/"])
    results = _fallback_with([first, second]).search("q", max_results=5)
    urls = [result.url for result in results]
    # URL dedupe: the trailing-slash duplicate of a2.com is not repeated.
    assert urls == ["https://a1.com", "https://a2.com", "https://b1.com"]
    assert [result.rank for result in results] == [1, 2, 3]


def test_fallback_skips_failed_layers_and_still_answers():
    first = _StubProvider("a", error="rate limited")
    second = _StubProvider("b", results=["https://b1.com"])
    results = _fallback_with([first, second]).search("q", max_results=5)
    assert [result.url for result in results] == ["https://b1.com"]


def test_fallback_raises_only_when_every_layer_failed_with_no_results():
    import pytest

    first = _StubProvider("a", error="boom")
    second = _StubProvider("b", error="bang")
    with pytest.raises(RuntimeError):
        _fallback_with([first, second]).search("q", max_results=5)


def test_fallback_real_chain_construction(monkeypatch, settings):
    settings.SEARCH_FALLBACK_PROVIDERS = "ddgs,bing_html"
    monkeypatch.setitem(
        fallback_provider._FREE_PROVIDER_REGISTRY,
        "ddgs",
        lambda: _StubProvider("ddgs", results=[]),
    )
    provider = FallbackSearchProvider()
    assert provider._providers  # constructed without touching the network
