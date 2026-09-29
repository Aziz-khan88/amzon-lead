from __future__ import annotations

from django.core.cache import cache

from leadfinder.services.books.free_catalogs import (
    crossref_isbn_record,
    internet_archive_isbn_record,
    wikidata_isbn_record,
)
from leadfinder.services.books.isbn_intelligence import resolve_free_metadata

ISBN13 = "9780306406157"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class AllCatalogsSession:
    """Serves every free catalog with the same book under exact-ISBN shapes."""

    def get(self, url, **kwargs):
        if "openlibrary.org" in url:
            return FakeResponse(
                {
                    f"ISBN:{ISBN13}": {
                        "title": "The Example Book",
                        "authors": [{"name": "Ada Author"}],
                        "publishers": [{"name": "Example Press"}],
                        "publish_date": "2025",
                        "url": "https://openlibrary.org/books/OL1M/The_Example_Book",
                    }
                }
            )
        if "googleapis.com" in url:
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
                                "industryIdentifiers": [
                                    {"type": "ISBN_10", "identifier": "0306406152"}
                                ],
                                "infoLink": "https://books.google.test/volume-1",
                            },
                        }
                    ]
                }
            )
        if "api.crossref.org" in url:
            return FakeResponse(
                {
                    "message": {
                        "items": [
                            {
                                "DOI": "10.0000/example",
                                "title": ["The Example Book"],
                                "author": [{"given": "Ada", "family": "Author"}],
                                "publisher": "Example Press",
                                "published": {"date-parts": [[2025, 3, 1]]},
                                "ISBN": [ISBN13],
                                "URL": "https://doi.org/10.0000/example",
                                "type": "book",
                            }
                        ]
                    }
                }
            )
        if "archive.org" in url:
            return FakeResponse(
                {
                    "response": {
                        "docs": [
                            {
                                "identifier": "examplebook0000ada",
                                "title": "The Example Book",
                                "creator": ["Ada Author"],
                                "date": "2025-03-01",
                                "publisher": "Example Press",
                            }
                        ]
                    }
                }
            )
        if "query.wikidata.org" in url:
            rows = [
                {
                    "item": {"value": "https://www.wikidata.org/entity/Q123"},
                    "itemLabel": {"value": "The Example Book"},
                    "authorLabel": {"value": "Ada Author"},
                    "publisherLabel": {"value": "Example Press"},
                    "date": {"value": "2025-03-01T00:00:00Z"},
                }
            ]
            return FakeResponse({"head": {}, "results": {"bindings": rows}})
        raise AssertionError(f"Unexpected URL in test: {url}")


def test_crossref_record_parses_publisher_deposited_metadata():
    record = crossref_isbn_record(AllCatalogsSession(), ISBN13)

    assert record is not None
    assert record["provider"] == "crossref"
    assert record["title"] == "The Example Book"
    assert record["authors"] == ["Ada Author"]
    assert record["publisher"] == "Example Press"
    assert record["publication_date"] == "2025"


def test_internet_archive_record_parses_scanned_catalog_entry():
    record = internet_archive_isbn_record(AllCatalogsSession(), ISBN13)

    assert record is not None
    assert record["provider"] == "internet_archive"
    assert record["title"] == "The Example Book"
    assert record["cover_image_url"] == "https://archive.org/services/img/examplebook0000ada"
    assert record["source_url"].endswith("/details/examplebook0000ada")


def test_wikidata_record_aggregates_author_rows():
    record = wikidata_isbn_record(AllCatalogsSession(), ISBN13)

    assert record is not None
    assert record["provider"] == "wikidata"
    assert record["title"] == "The Example Book"
    assert record["authors"] == ["Ada Author"]
    assert record["publication_date"] == "2025"


def test_new_fetchers_reject_wrong_response_shapes():
    class GarbageSession:
        def get(self, url, **kwargs):
            return FakeResponse({"items": [{"volumeInfo": {}}]})

    session = GarbageSession()
    assert crossref_isbn_record(session, ISBN13) is None
    assert internet_archive_isbn_record(session, ISBN13) is None
    assert wikidata_isbn_record(session, ISBN13) is None


def test_resolve_free_metadata_merges_all_five_free_sources():
    cache.clear()
    result = resolve_free_metadata(ISBN13, session=AllCatalogsSession())

    assert {source["provider"] for source in result["sources"]} == {
        "open_library",
        "google_books",
        "crossref",
        "internet_archive",
        "wikidata",
    }
    assert result["metadata"]["title"] == "The Example Book"
    assert result["metadata"]["authors"] == ["Ada Author"]
    assert result["field_evidence"]["title"]["agreement"] == 1.0
    assert result["confidence"] >= 0.9
