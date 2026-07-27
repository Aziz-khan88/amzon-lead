from __future__ import annotations

from django.core.cache import cache

from leadfinder.services.books.library_of_congress_provider import search_library_of_congress


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return FakeResponse(self.payload)


def test_loc_discovery_filters_year_invalid_ids_and_deduplicates_equivalent_isbns():
    cache.clear()
    payload = {
        "results": [
            {
                "title": "The Moon Book",
                "contributor": ["Alice Author"],
                "number_isbn": ["978-0-306-40615-7 (hardcover)"],
                "date": "2024",
                "id": "https://www.loc.gov/item/one/",
                "subject": ["Children's stories"],
            },
            {
                "title": "The Moon Book duplicate edition",
                "contributor": ["Alice Author"],
                "number_isbn": ["0306406152"],
                "date": "2024",
                "id": "https://www.loc.gov/item/two/",
            },
            {
                "title": "Wrong year",
                "contributor": ["Bob Author"],
                "number_isbn": ["0471958697"],
                "date": "2010",
            },
            {
                "title": "Bad checksum",
                "contributor": ["Bad Author"],
                "number_isbn": ["9780306406158"],
                "date": "2024",
            },
        ]
    }
    session = FakeSession(payload)

    results = search_library_of_congress(
        "moon children",
        year_start=2023,
        year_end=2025,
        max_books=10,
        session=session,
    )

    assert len(results) == 1
    assert results[0]["isbn"] == "9780306406157"
    assert results[0]["source"] == "library_of_congress"
    assert session.calls == 1


def test_loc_discovery_reuses_django_cache():
    cache.clear()
    payload = {
        "results": [
            {
                "title": "Cached Book",
                "contributor": ["Alice Author"],
                "number_isbn": ["9780306406157"],
                "date": "2024",
            }
        ]
    }
    session = FakeSession(payload)

    first = search_library_of_congress("cached moon", max_books=1, session=session)
    second = search_library_of_congress("cached moon", max_books=1, session=session)

    assert first == second
    assert session.calls == 1
