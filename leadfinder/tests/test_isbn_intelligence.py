from __future__ import annotations

import pytest
from django.core.cache import cache
from django.urls import reverse

from leadfinder.services.books.isbn_intelligence import (
    analyze_identifier,
    generate_barcode_svg,
    parse_identifier_batch,
    resolve_free_metadata,
)


@pytest.mark.parametrize(
    ("value", "kind", "canonical"),
    [
        ("0-306-40615-2", "isbn10", "0306406152"),
        ("978-0-306-40615-7", "isbn13", "9780306406157"),
        ("979-10-90636-07-1", "isbn13", "9791090636071"),
        ("B0NEWASINX", "asin", "B0NEWASINX"),
        ("https://www.amazon.com/dp/B012345678", "asin", "B012345678"),
    ],
)
def test_identifier_analysis_accepts_supported_formats(value, kind, canonical):
    result = analyze_identifier(value)

    assert result.valid is True
    assert result.identifier_type == kind
    assert result.canonical == canonical


@pytest.mark.parametrize(
    "value", ["9780306406158", "0306406153", "BOOKSTORES", "garbage"]
)
def test_identifier_analysis_rejects_bad_checksums_and_non_book_tokens(value):
    assert analyze_identifier(value).valid is False


def test_identifier_batch_dedupes_equivalent_isbn10_and_isbn13():
    valid, invalid = parse_identifier_batch("0-306-40615-2, 9780306406157\nB0NEWASINX")

    assert [item.canonical for item in valid] == ["0306406152", "B0NEWASINX"]
    assert invalid == []


def test_barcode_generation_returns_svg_for_isbn10_conversion():
    svg = generate_barcode_svg("0306406152")

    assert svg.startswith(b"<?xml")
    assert b"9780306406157" in svg


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class CatalogSession:
    def get(self, url, **kwargs):
        if "openlibrary.org" in url:
            return FakeResponse(
                {
                    "ISBN:9780306406157": {
                        "title": "The Example Book",
                        "authors": [{"name": "Ada Author"}],
                        "publishers": [{"name": "Example Press"}],
                        "publish_date": "2025",
                        "url": "https://openlibrary.org/books/OL1M/The_Example_Book",
                    }
                }
            )
        return FakeResponse(
            {
                "items": [
                    {
                        "id": "volume-1",
                        "volumeInfo": {
                            "title": "The Example Book",
                            "authors": ["Ada Author"],
                            "publisher": "Example Press",
                            "publishedDate": "2025",
                            # Exact-match logic must accept the ISBN-10 alias.
                            "industryIdentifiers": [
                                {"type": "ISBN_10", "identifier": "0306406152"}
                            ],
                            "infoLink": "https://books.google.test/volume-1",
                        },
                    }
                ]
            }
        )


def test_free_metadata_resolution_reconciles_exact_identifier_aliases():
    cache.clear()
    result = resolve_free_metadata("9780306406157", session=CatalogSession())

    assert result["metadata"]["title"] == "The Example Book"
    assert result["metadata"]["authors"] == ["Ada Author"]
    assert result["confidence"] >= 0.85
    assert {source["provider"] for source in result["sources"]} == {
        "open_library",
        "google_books",
    }
    assert result["field_evidence"]["title"]["agreement"] == 1.0


def test_legacy_free_metadata_helper_uses_exact_identifier_reconciliation(monkeypatch):
    from leadfinder.services.amazon.amazon_scraper import fetch_metadata_from_free_apis
    from leadfinder.services.books import isbn_intelligence

    original_resolve = isbn_intelligence.resolve_free_metadata
    monkeypatch.setattr(
        isbn_intelligence,
        "resolve_free_metadata",
        lambda identifier: original_resolve(identifier, session=CatalogSession()),
    )
    cache.clear()

    result = fetch_metadata_from_free_apis("9780306406157")

    assert result is not None
    assert result["title"] == "The Example Book"
    assert result["authors"] == [{"name": "Ada Author", "url": ""}]

def test_analyze_and_barcode_routes(client, db):
    analyze_response = client.get(
        reverse("leadfinder:isbn_analyze"), {"identifier": "9780306406157"}
    )
    barcode_response = client.get(
        reverse("leadfinder:isbn_barcode", args=["9780306406157"])
    )

    assert analyze_response.status_code == 200
    assert analyze_response.json()["isbn10"] == "0306406152"
    assert analyze_response.json()["barcode_url"].endswith("9780306406157.svg")
    assert barcode_response.status_code == 200
    assert barcode_response["Content-Type"] == "image/svg+xml"


def test_direct_search_rejects_invalid_identifier_without_creating_run(client, db):
    from leadfinder.models import ResearchRun

    response = client.post(
        reverse("leadfinder:isbn_search"),
        {
            "isbn": "9780306406158",
            "run_video_search": False,
            "run_groq_ai_extraction": False,
        },
    )

    assert response.status_code == 200
    assert "Invalid identifier" in response.content.decode()
    assert ResearchRun.objects.count() == 0
