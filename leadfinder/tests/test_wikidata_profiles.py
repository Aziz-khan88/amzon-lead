from __future__ import annotations

from django.core.cache import cache

from leadfinder.services.social.wikidata_profiles import find_author_profiles


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _claim(value: str):
    return {"mainsnak": {"datavalue": {"value": value}}}


class WikidataSession:
    """Two-call fake: wbsearchentities then wbgetentities."""

    def get(self, url, params=None, **kwargs):
        params = params or {}
        if params.get("action") == "wbsearchentities":
            return FakeResponse(
                {
                    "search": [
                        {
                            "id": "Q42",
                            "label": "Ada Author",
                            "description": "children's author and illustrator",
                        },
                        {
                            "id": "Q99",
                            "label": "Ada Author",
                            "description": "software engineer",
                        },
                    ]
                }
            )
        if params.get("action") == "wbgetentities":
            return FakeResponse(
                {
                    "entities": {
                        params.get("ids", ""): {
                            "claims": {
                                "P856": [_claim("https://adaauthor.example.com")],
                                "P2003": [_claim("ada.author")],
                                "P2397": [_claim("UCabcdefghijk")],
                                "P2963": [_claim("12345")],
                            },
                            "sitelinks": {"enwiki": {"title": "Ada Author"}},
                        }
                    }
                }
            )
        raise AssertionError(f"Unexpected Wikidata call: {params}")


class NoMatchSession:
    def get(self, url, params=None, **kwargs):
        return FakeResponse({"search": [{"id": "Q7", "label": "Someone Else", "description": "author"}]})


class NoProfilesSession:
    def get(self, url, params=None, **kwargs):
        params = params or {}
        if params.get("action") == "wbsearchentities":
            return FakeResponse(
                {"search": [{"id": "Q8", "label": "Ada Author", "description": "writer"}]}
            )
        return FakeResponse({"entities": {"Q8": {"claims": {}, "sitelinks": {}}}})


def setup_function():
    cache.clear()


def test_find_author_profiles_maps_claims_to_urls():
    profiles = find_author_profiles("Ada Author", session=WikidataSession())

    assert profiles is not None
    assert profiles["entity_id"] == "Q42"
    assert profiles["confidence"] == 0.8  # description mentions author
    assert profiles["canonical_website"] == "https://adaauthor.example.com"
    assert profiles["instagram_url"] == "https://www.instagram.com/ada.author"
    assert profiles["youtube_url"] == "https://www.youtube.com/channel/UCabcdefghijk"
    assert profiles["goodreads_url"] == "https://www.goodreads.com/author/show/12345"
    assert profiles["wikipedia_url"] == "https://en.wikipedia.org/wiki/Ada_Author"


def test_find_author_profiles_rejects_label_mismatch():
    assert find_author_profiles("Ada Author", session=NoMatchSession()) is None


def test_find_author_profiles_returns_none_without_any_profile():
    assert find_author_profiles("Ada Author", session=NoProfilesSession()) is None


def test_find_author_profiles_caches_results():
    profiles = find_author_profiles("Ada Author", session=WikidataSession())
    assert profiles is not None
    # Second call must come from cache; a broken session would raise.
    cached = find_author_profiles("Ada Author", session=NoMatchSession())
    assert cached == profiles
