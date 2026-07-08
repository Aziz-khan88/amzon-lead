from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.test import override_settings

from leadfinder.services.search.base import SearchResultDTO


@dataclass
class FakeClassification:
    is_childrens_book: bool | None = True
    is_picture_or_illustrated_book: bool | None = True
    confidence: float = 0.88
    age_range_guess: str | None = "4-8"
    reason: str = "Test AI analysis"
    reject_reason: str | None = None


class FakeDDGSProvider:
    provider_name = "ddgs"
    calls = 0

    def search(self, query, max_results=10):
        self.__class__.calls += 1
        if self.__class__.calls == 1:
            return [
                SearchResultDTO(
                    title="Saved Book by Alice Author",
                    url="https://www.amazon.com/dp/0306406152",
                    snippet="A children picture book by Alice Author",
                    rank=1,
                    provider="ddgs",
                )
            ]
        return [
                SearchResultDTO(
                    title="Fresh Book by Bob Author",
                    url="https://www.amazon.com/dp/0471958697",
                    snippet="An illustrated children book by Bob Author",
                    rank=1,
                    provider="ddgs",
            )
        ]


class EmptyHTMLProvider:
    provider_name = "ddgs_html"

    def __init__(self, delay=0):
        self.delay = delay

    def search(self, query, max_results=10):
        return []


class EmptyGoogleBooksProvider:
    def discover_books(self, keyword, max_books=25):
        return []


class EmptyGroqClient:
    def complete_json(self, *args, **kwargs):
        return None


@pytest.mark.django_db
def test_keyword_lookup_saves_and_reuses_keyword_folder(tmp_path, monkeypatch):
    from leadfinder.services.books import isbn_keyword_lookup as lookup

    FakeDDGSProvider.calls = 0
    monkeypatch.setattr(lookup, "DDGSSearchProvider", FakeDDGSProvider)
    monkeypatch.setattr(lookup, "DDGHTMLSearchProvider", EmptyHTMLProvider)
    monkeypatch.setattr(lookup, "classify_book", lambda *args, **kwargs: FakeClassification())
    monkeypatch.setattr(lookup, "fetch_metadata_from_free_apis", lambda asin: None)
    monkeypatch.setattr(lookup, "search_openlibrary", lambda *args, **kwargs: [])
    monkeypatch.setattr(lookup, "GoogleBooksProvider", EmptyGoogleBooksProvider)
    monkeypatch.setattr(lookup, "GroqJSONClient", EmptyGroqClient)

    with override_settings(BASE_DIR=tmp_path):
        first_events = list(lookup.stream_keyword_lookup("dragon bedtime", "", "", 1))
        first_done = first_events[-1]
        assert first_done["status"] == "done"
        assert first_done["count"] == 1

        cache_file = tmp_path / "data" / "isbn_keyword_database" / "dragon-bedtime" / "any-any_results.json"
        isbn_file = tmp_path / "data" / "isbn_keyword_database" / "dragon-bedtime" / "any-any_isbns.csv"
        assert cache_file.exists()
        assert isbn_file.exists()

        second_events = list(lookup.stream_keyword_lookup("dragon bedtime", "", "", 2))
        progress_events = [event for event in second_events if event["status"] == "progress"]

        assert progress_events[0]["cache_hit"] is True
        assert progress_events[0]["books"][0]["asin"] == "0306406152"
        assert second_events[-1]["count"] == 2

        cached_books = lookup.load_cached_books("dragon bedtime", None, None)
        assert [book["asin"] for book in cached_books] == ["0306406152", "0471958697"]
        assert cached_books[0]["ai_analysis"]["reason"] == "Test AI analysis"
        assert cached_books[0]["identifier_type"] == "isbn10"
        assert cached_books[0]["validation_score"] > 0.5
        assert cached_books[0]["ai_layer"] == "groq_metadata_refinement_and_book_fit"
        assert "groq_ai_book_fit_scoring" in cached_books[0]["analysis_layers"]


def test_candidate_from_search_result_extracts_catalog_isbn(monkeypatch):
    from leadfinder.services.books import isbn_keyword_lookup as lookup

    monkeypatch.setattr(lookup, "classify_book", lambda *args, **kwargs: FakeClassification())
    monkeypatch.setattr(lookup, "fetch_metadata_from_free_apis", lambda asin: None)
    monkeypatch.setattr(lookup, "GroqJSONClient", EmptyGroqClient)

    dto = SearchResultDTO(
        title="Dragon Bedtime Picture Book ISBN 9781234567897",
        url="https://isbnsearch.org/isbn/9781234567897",
        snippet="A children picture book by Alice Author. ISBN: 978-1-234-56789-7",
        rank=1,
        provider="ddgs",
    )

    candidate = lookup.candidate_from_search_result(dto, "ddgs", None, None)

    assert candidate is not None
    assert candidate["asin"] == "9781234567897"
    assert candidate["source"] == "ddgs"
    assert "valid_isbn13" in candidate["analysis_layers"]


def test_catalog_candidate_keeps_structured_valid_isbn(monkeypatch):
    from leadfinder.services.books import isbn_keyword_lookup as lookup

    monkeypatch.setattr(lookup, "classify_book", lambda *args, **kwargs: FakeClassification())
    monkeypatch.setattr(lookup, "fetch_metadata_from_free_apis", lambda asin: None)
    monkeypatch.setattr(lookup, "GroqJSONClient", EmptyGroqClient)

    candidate = lookup.candidate_from_catalog_result(
        {
            "title": "A Small Moon",
            "author_name": "Alice Author",
            "isbn": "9781234567897",
            "publication_date": "2024",
            "cover_image_url": "https://example.com/cover.jpg",
        },
        "open_library",
    )

    assert candidate is not None
    assert candidate["asin"] == "9781234567897"
    assert candidate["author_name"] == "Alice Author"
    assert candidate["validation_score"] > 0.5


def test_invalid_isbn_checksum_is_rejected():
    from leadfinder.services.books import isbn_keyword_lookup as lookup

    assert lookup.normalize_book_code("9781234567890") == ""
    assert lookup.normalize_book_code("BOOKSTORES") == ""
    assert lookup.normalize_book_code("BUMBLEBEAR") == ""


def test_extracts_text_asin(monkeypatch):
    from leadfinder.services.books import isbn_keyword_lookup as lookup

    monkeypatch.setattr(lookup, "classify_book", lambda *args, **kwargs: FakeClassification())
    monkeypatch.setattr(lookup, "fetch_metadata_from_free_apis", lambda asin: None)
    monkeypatch.setattr(lookup, "GroqJSONClient", EmptyGroqClient)

    dto = SearchResultDTO(
        title="A new children picture book ASIN B0DBZV185Z",
        url="https://example.com/book",
        snippet="Illustrated storybook by Alice Author, Amazon ASIN B0DBZV185Z.",
        rank=1,
        provider="ddgs",
    )

    candidate = lookup.candidate_from_search_result(dto, "ddgs", None, None)

    assert candidate is not None
    assert candidate["asin"] == "B0DBZV185Z"
    assert candidate["identifier_type"] == "asin"


def test_old_year_is_rejected_when_year_filter_is_set(monkeypatch):
    from leadfinder.services.books import isbn_keyword_lookup as lookup

    monkeypatch.setattr(lookup, "classify_book", lambda *args, **kwargs: FakeClassification())
    monkeypatch.setattr(lookup, "fetch_metadata_from_free_apis", lambda asin: None)
    monkeypatch.setattr(lookup, "GroqJSONClient", EmptyGroqClient)

    candidate = lookup.candidate_from_catalog_result(
        {
            "title": "The illustrated mum",
            "author_name": "Jacqueline Wilson",
            "isbn": "9780440863687",
            "publication_date": "2000",
        },
        "open_library",
        year_start=2025,
        year_end=2026,
    )

    assert candidate is None


def test_cached_bad_rows_are_filtered(tmp_path):
    from leadfinder.services.books import isbn_keyword_lookup as lookup

    cache_dir = tmp_path / "data" / "isbn_keyword_database" / "children-book-illustration"
    cache_dir.mkdir(parents=True)
    (cache_dir / "2025-2026_results.json").write_text(
        """
        {
          "books": [
            {"asin": "BOOKSTORES", "title": "Shop Bestselling Kids Books", "author_name": "Unknown Author", "publication_date": ""},
            {"asin": "9780440863687", "title": "The illustrated mum", "author_name": "Jacqueline Wilson", "publication_date": "2000"},
            {"asin": "9781234567897", "title": "Good 2025 Book", "author_name": "Alice Author", "publication_date": "2025"}
          ]
        }
        """,
        encoding="utf-8",
    )

    with override_settings(BASE_DIR=tmp_path):
        books = lookup.load_cached_books("children book illustration", 2025, 2026)

    assert [book["asin"] for book in books] == ["9781234567897"]


@pytest.mark.django_db
def test_keyword_lookup_only_new_excludes_cache(tmp_path, monkeypatch):
    from leadfinder.services.books import isbn_keyword_lookup as lookup

    FakeDDGSProvider.calls = 0
    monkeypatch.setattr(lookup, "DDGSSearchProvider", FakeDDGSProvider)
    monkeypatch.setattr(lookup, "DDGHTMLSearchProvider", EmptyHTMLProvider)
    monkeypatch.setattr(lookup, "classify_book", lambda *args, **kwargs: FakeClassification())
    monkeypatch.setattr(lookup, "fetch_metadata_from_free_apis", lambda asin: None)
    monkeypatch.setattr(lookup, "search_openlibrary", lambda *args, **kwargs: [])
    monkeypatch.setattr(lookup, "GoogleBooksProvider", EmptyGoogleBooksProvider)
    monkeypatch.setattr(lookup, "GroqJSONClient", EmptyGroqClient)

    with override_settings(BASE_DIR=tmp_path):
        # 1. Populate the cache first
        list(lookup.stream_keyword_lookup("dragon bedtime", "", "", 1, only_new=False))

        cache_file = tmp_path / "data" / "isbn_keyword_database" / "dragon-bedtime" / "any-any_results.json"
        assert cache_file.exists()

        # 2. Run with only_new=True
        events = list(lookup.stream_keyword_lookup("dragon bedtime", "", "", 1, only_new=True))
        
        # Verify no cache loaded/progress event yielding the old book is present
        progress_events = [event for event in events if event["status"] == "progress"]
        
        # There should be exactly 1 progress event for the new book found (Bob Author), none for the cache (Alice Author)
        assert len(progress_events) == 1
        assert progress_events[0]["books"][0]["asin"] == "0471958697"  # Fresh Book by Bob Author
        assert progress_events[0].get("cache_hit") is None
        
        # Verify done count is 1 (for 1 new book)
        assert events[-1]["count"] == 1
