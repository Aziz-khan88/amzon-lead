from __future__ import annotations

from leadfinder.models import ResearchRun
from leadfinder.services.books.google_books_provider import GoogleBooksProvider
from leadfinder.services.pipeline.run_research import discover_books_from_keyword


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            from requests import HTTPError

            error = HTTPError(f"{self.status_code} error")
            error.response = self
            raise error
        return None

    def json(self):
        return self.payload


def google_books_candidate():
    return {
        "title": "Moon Bunny",
        "author_name": "Avery Moon",
        "asin": "9781234567890",
        "amazon_book_url": "",
        "amazon_source_url": "https://books.google.com/books?id=vol-1",
        "amazon_source_title": "Moon Bunny",
        "amazon_source_snippet": "A children's picture book for bedtime reading.",
        "category": "Juvenile Fiction / Bedtime & Dreams",
        "review_count": 12,
        "rating": 4.5,
        "publisher": "Little Lantern Press",
        "publication_date": "2024-02-01",
        "cover_image_url": "https://books.google.com/cover.jpg",
        "book_data_confidence": 0.95,
        "source_provider": "google_books",
        "source_raw_json": {"google_volume_id": "vol-1"},
    }


def test_google_books_provider_extracts_high_quality_childrens_book(monkeypatch):
    payload = {
        "items": [
            {
                "id": "vol-1",
                "selfLink": "https://www.googleapis.com/books/v1/volumes/vol-1",
                "volumeInfo": {
                    "title": "Moon Bunny",
                    "subtitle": "A Bedtime Picture Book",
                    "authors": ["Avery Moon"],
                    "publisher": "Little Lantern Press",
                    "publishedDate": "2024-02-01",
                    "description": "A children's picture book for bedtime reading.",
                    "categories": ["Juvenile Fiction / Bedtime & Dreams"],
                    "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9781234567890"}],
                    "averageRating": 4.5,
                    "ratingsCount": 12,
                    "imageLinks": {"thumbnail": "http://books.google.com/cover.jpg"},
                    "canonicalVolumeLink": "https://books.google.com/books?id=vol-1",
                },
            }
        ]
    }
    monkeypatch.setattr(
        "leadfinder.services.books.google_books_provider.requests.get",
        lambda *args, **kwargs: FakeResponse(payload),
    )

    books = GoogleBooksProvider(api_key="test-key").discover_books("bedtime picture book", max_books=1)

    assert len(books) == 1
    book = books[0]
    assert book["title"] == "Moon Bunny: A Bedtime Picture Book"
    assert book["author_name"] == "Avery Moon"
    assert book["asin"] == "9781234567890"
    assert book["publisher"] == "Little Lantern Press"
    assert book["cover_image_url"].startswith("https://")
    assert book["book_data_confidence"] >= 0.9


def test_google_books_provider_rejects_items_without_author(monkeypatch):
    payload = {
        "items": [
            {
                "id": "weak",
                "volumeInfo": {
                    "title": "Generic Drawing Guide",
                    "description": "A book with no reliable author metadata.",
                    "categories": ["Art"],
                },
            }
        ]
    }
    monkeypatch.setattr(
        "leadfinder.services.books.google_books_provider.requests.get",
        lambda *args, **kwargs: FakeResponse(payload),
    )

    assert GoogleBooksProvider(api_key="test-key").discover_books("drawing", max_books=1) == []


def test_google_books_provider_retries_without_restricted_key(monkeypatch):
    calls = []
    payload = {
        "items": [
            {
                "id": "vol-1",
                "volumeInfo": {
                    "title": "Moon Bunny",
                    "authors": ["Avery Moon"],
                    "description": "A children's picture book.",
                    "categories": ["Juvenile Fiction"],
                },
            }
        ]
    }

    def fake_get(url, **kwargs):
        calls.append(url)
        if "key=" in url:
            return FakeResponse({}, status_code=403)
        return FakeResponse(payload)

    monkeypatch.setattr("leadfinder.services.books.google_books_provider.requests.get", fake_get)

    books = GoogleBooksProvider(api_key="restricted-key").discover_books("picture book", max_books=1)

    assert len(books) == 1
    assert "key=" in calls[0]
    assert "key=" not in calls[1]


def test_google_books_provider_records_query_errors(monkeypatch):
    def fake_get(url, **kwargs):
        return FakeResponse({}, status_code=429)

    monkeypatch.setattr("leadfinder.services.books.google_books_provider.requests.get", fake_get)

    provider = GoogleBooksProvider(api_key="")
    assert provider.discover_books("picture book", max_books=1) == []
    assert provider.last_errors
    assert "429 error" in provider.last_errors[0]


def test_ddgs_discovery_falls_back_to_google_books_when_web_search_fails(db, monkeypatch):
    class BrokenSearchProvider:
        provider_name = "ddgs"

        def search(self, query, max_results=10):
            raise RuntimeError("DDGS search failed: ConnectError")

    monkeypatch.setattr("leadfinder.services.pipeline.run_research.get_search_provider", lambda name=None: BrokenSearchProvider())
    monkeypatch.setattr("leadfinder.services.pipeline.run_research.GoogleBooksProvider.is_configured", lambda self: True)
    monkeypatch.setattr(
        "leadfinder.services.pipeline.run_research.GoogleBooksProvider.discover_books",
        lambda self, keyword, max_books=25: [google_books_candidate()],
    )
    run = ResearchRun.objects.create(keyword="Children books illustration", source_provider="ddgs", max_books=1)

    books = discover_books_from_keyword(run)

    assert len(books) == 1
    assert books[0].source_provider == "google_books"
    assert books[0].title == "Moon Bunny"
    assert run.search_logs.filter(provider="ddgs", status="failed").exists()
    assert run.search_logs.filter(provider="google_books", status="success").exists()
