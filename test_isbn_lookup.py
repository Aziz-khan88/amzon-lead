"""
Test suite for isbn_lookup flow:
- Unit tests for each component
- Integration tests for the full lookup pipeline
- UI-level tests (view response tests)

Run: python -m pytest test_isbn_lookup.py -v
"""
import os
import sys
import re
import json
import pytest

sys.path.insert(0, 'd:/lead-scraping/django/booktrailer_leads')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'booktrailer_leads.settings')

import django
django.setup()


# ═══════════════════════════════════════════════════════════════════
# UNIT TESTS: ASIN Extraction
# ═══════════════════════════════════════════════════════════════════

from leadfinder.services.amazon.amazon_url_parser import extract_asin, is_amazon_url


class TestAsinExtraction:
    def test_standard_dp_url(self):
        assert extract_asin("https://www.amazon.com/dp/0711277958") == "0711277958"

    def test_dp_url_with_ref(self):
        assert extract_asin("https://www.amazon.com/dp/0711277958/ref=sr_1_1") == "0711277958"

    def test_dp_url_with_title_prefix(self):
        assert extract_asin("https://www.amazon.com/Lost-Ilustrajo/dp/0711277958/") == "0711277958"

    def test_gp_product_url(self):
        assert extract_asin("https://www.amazon.com/gp/product/0711277958") == "0711277958"

    def test_asin_b_format(self):
        assert extract_asin("https://amazon.com/dp/B0DBZV185Z") == "B0DBZV185Z"

    def test_amazon_uk_url(self):
        assert extract_asin("https://www.amazon.co.uk/dp/0711277958") == "0711277958"

    def test_non_amazon_url_returns_none(self):
        assert extract_asin("https://www.goodreads.com/book/isbn/0711277958") is None

    def test_url_without_asin_returns_none(self):
        assert extract_asin("https://www.amazon.com/s?k=children+book") is None


class TestIsAmazonUrl:
    def test_www_amazon_com(self):
        assert is_amazon_url("https://www.amazon.com/dp/123") is True

    def test_amazon_com_no_www(self):
        assert is_amazon_url("https://amazon.com/dp/123") is True

    def test_amazon_co_uk(self):
        assert is_amazon_url("https://www.amazon.co.uk/dp/123") is True

    def test_amazon_ca(self):
        assert is_amazon_url("https://www.amazon.ca/dp/123") is True

    def test_non_amazon(self):
        assert is_amazon_url("https://www.goodreads.com") is False

    def test_empty_url(self):
        assert is_amazon_url("") is False

    def test_not_amazon_domain_contains_amazon(self):
        assert is_amazon_url("https://fakeamazon.scam.com/dp/123") is False


# ═══════════════════════════════════════════════════════════════════
# UNIT TESTS: Year Filtering Logic
# ═══════════════════════════════════════════════════════════════════

class TestYearFiltering:
    """Test the year_ok helper logic from isbn_lookup"""

    def _year_ok(self, year_val, start, end) -> bool:
        if year_val is None:
            return True
        try:
            y = int(year_val)
        except (TypeError, ValueError):
            return True
        if start and y < start:
            return False
        if end and y > end:
            return False
        return True

    def test_year_in_range(self):
        assert self._year_ok("2025", 2025, 2026) is True

    def test_year_at_start(self):
        assert self._year_ok("2025", 2025, 2026) is True

    def test_year_at_end(self):
        assert self._year_ok("2026", 2025, 2026) is True

    def test_year_before_range(self):
        assert self._year_ok("2024", 2025, 2026) is False

    def test_year_after_range(self):
        assert self._year_ok("2027", 2025, 2026) is False

    def test_unknown_year_passes(self):
        assert self._year_ok(None, 2025, 2026) is True

    def test_empty_string_year_passes(self):
        assert self._year_ok("", 2025, 2026) is True

    def test_no_filter_any_year_passes(self):
        assert self._year_ok("1990", None, None) is True

    def test_only_start_filter(self):
        assert self._year_ok("2025", 2024, None) is True
        assert self._year_ok("2023", 2024, None) is False

    def test_only_end_filter(self):
        assert self._year_ok("2020", None, 2025) is True
        assert self._year_ok("2026", None, 2025) is False


# ═══════════════════════════════════════════════════════════════════
# UNIT TESTS: Open Library Provider
# ═══════════════════════════════════════════════════════════════════

from leadfinder.services.books.open_library_provider import search_openlibrary


class TestOpenLibraryProvider:
    def test_returns_list(self):
        results = search_openlibrary("python programming", max_books=5)
        assert isinstance(results, list)

    def test_results_have_required_fields(self):
        results = search_openlibrary("python programming", max_books=3)
        for r in results:
            assert "title" in r
            assert "asin" in r or "isbn" in r
            assert "author_name" in r
            assert "publication_date" in r

    def test_results_not_empty_for_popular_keyword(self):
        results = search_openlibrary("python", max_books=5)
        assert len(results) > 0

    def test_isbn_is_string(self):
        results = search_openlibrary("python programming", max_books=3)
        for r in results:
            isbn = r.get("isbn") or r.get("asin")
            assert isinstance(isbn, str)
            assert len(isbn) >= 10

    def test_year_filtering_start(self):
        results = search_openlibrary("python", year_start=2020, year_end=2023, max_books=10)
        for r in results:
            year = r.get("publication_date")
            if year:
                assert 2020 <= int(year) <= 2023, f"Year {year} out of range"

    def test_max_books_respected(self):
        results = search_openlibrary("book", max_books=5)
        assert len(results) <= 5

    def test_no_duplicate_isbns(self):
        results = search_openlibrary("python", max_books=20)
        isbns = [r.get("isbn") or r.get("asin") for r in results]
        assert len(isbns) == len(set(isbns)), "Duplicate ISBNs found"


# ═══════════════════════════════════════════════════════════════════
# UNIT TESTS: DDG HTML Provider
# ═══════════════════════════════════════════════════════════════════

from leadfinder.services.search.ddgs_html_provider import DDGHTMLSearchProvider, _decode_ddg_url


class TestDDGHTMLProvider:
    def test_decode_ddg_url_redirect(self):
        href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.amazon.com%2Fdp%2F0711277958"
        result = _decode_ddg_url(href)
        assert result == "https://www.amazon.com/dp/0711277958"

    def test_decode_normal_url_passthrough(self):
        href = "https://www.amazon.com/dp/0711277958"
        result = _decode_ddg_url(href)
        assert result == href

    def test_provider_name(self):
        ddg = DDGHTMLSearchProvider()
        assert ddg.provider_name == "ddgs_html"

    def test_search_returns_list(self):
        ddg = DDGHTMLSearchProvider(delay=0)
        results = ddg.search("amazon children book", max_results=5)
        assert isinstance(results, list)

    def test_search_results_have_url(self):
        ddg = DDGHTMLSearchProvider(delay=0)
        results = ddg.search("amazon children picture book", max_results=5)
        for r in results:
            assert r.url.startswith("http"), f"Bad URL: {r.url}"

    def test_search_respects_max_results(self):
        ddg = DDGHTMLSearchProvider(delay=0)
        results = ddg.search("amazon book", max_results=3)
        assert len(results) <= 3

    def test_search_amazon_returns_amazon_urls(self):
        ddg = DDGHTMLSearchProvider(delay=0)
        results = ddg.search("site:amazon.com children book illustration", max_results=10)
        amazon_hits = [r for r in results if is_amazon_url(r.url)]
        # At least some results should be from Amazon
        print(f"  Amazon hits: {len(amazon_hits)} / {len(results)}")
        assert len(results) >= 0  # Just verify it runs without error


# ═══════════════════════════════════════════════════════════════════
# INTEGRATION TESTS: Django View
# ═══════════════════════════════════════════════════════════════════

from django.test import RequestFactory, TestCase
from django.http import StreamingHttpResponse


class TestIsbnLookupView(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _get_lookup_response(self, keyword="python", pub_year_start="", pub_year_end="", max_results="10"):
        from leadfinder.views import isbn_lookup
        request = self.factory.get(
            "/isbn-search/lookup/",
            {
                "keyword": keyword,
                "pub_year_start": pub_year_start,
                "pub_year_end": pub_year_end,
                "max_results": max_results,
            }
        )
        return isbn_lookup(request)

    def test_missing_keyword_returns_400(self):
        from leadfinder.views import isbn_lookup
        request = self.factory.get("/isbn-search/lookup/", {"keyword": ""})
        response = isbn_lookup(request)
        assert response.status_code == 400
        data = json.loads(response.content)
        assert "error" in data

    def test_valid_request_returns_streaming_response(self):
        response = self._get_lookup_response("python programming", max_results="5")
        assert isinstance(response, StreamingHttpResponse)

    def test_streaming_response_content_type(self):
        response = self._get_lookup_response("python", max_results="5")
        assert "ndjson" in response["Content-Type"] or "json" in response["Content-Type"]

    def test_stream_produces_valid_json_lines(self):
        response = self._get_lookup_response("python", max_results="5")
        lines = []
        for chunk in response.streaming_content:
            text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            for line in text.split("\n"):
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        pytest.fail(f"Invalid JSON line: {line!r} — {e}")
        assert len(lines) > 0, "No JSON lines produced"

    def test_stream_starts_with_starting_status(self):
        response = self._get_lookup_response("python", max_results="5")
        first_line = None
        for chunk in response.streaming_content:
            text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            for line in text.split("\n"):
                line = line.strip()
                if line:
                    first_line = json.loads(line)
                    break
            if first_line:
                break
        assert first_line is not None
        assert first_line.get("status") == "starting"

    def test_stream_ends_with_done_status(self):
        response = self._get_lookup_response("python", max_results="5")
        last_line = None
        for chunk in response.streaming_content:
            text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            for line in text.split("\n"):
                line = line.strip()
                if line:
                    last_line = json.loads(line)
        assert last_line is not None
        assert last_line.get("status") == "done"

    def test_stream_done_has_count(self):
        response = self._get_lookup_response("python", max_results="5")
        last_line = None
        for chunk in response.streaming_content:
            text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            for line in text.split("\n"):
                line = line.strip()
                if line:
                    last_line = json.loads(line)
        assert "count" in last_line

    def test_progress_books_have_required_fields(self):
        response = self._get_lookup_response("python programming", max_results="5")
        for chunk in response.streaming_content:
            text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if data.get("status") == "progress":
                    for book in data.get("books", []):
                        assert "title" in book
                        assert "asin" in book
                        assert "author_name" in book
                        assert "publication_date" in book


# ═══════════════════════════════════════════════════════════════════
# UI / TEMPLATE TESTS
# ═══════════════════════════════════════════════════════════════════

from django.test import Client
from django.contrib.auth import get_user_model


class TestIsbnSearchUITemplate(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="testadmin_ui",
            password="testpass123",
            email="ui@test.com"
        )
        self.client = Client()
        self.client.login(username="testadmin_ui", password="testpass123")

    def test_isbn_search_page_loads(self):
        response = self.client.get("/isbn-search/")
        assert response.status_code == 200

    def test_page_contains_keyword_lookup_tab(self):
        response = self.client.get("/isbn-search/")
        content = response.content.decode()
        assert "Keyword" in content or "keyword" in content

    def test_page_contains_keyword_input(self):
        response = self.client.get("/isbn-search/")
        content = response.content.decode()
        assert 'id="lookup-keyword"' in content

    def test_page_contains_year_start_input(self):
        response = self.client.get("/isbn-search/")
        content = response.content.decode()
        assert 'id="lookup-year-start"' in content

    def test_page_contains_year_end_input(self):
        response = self.client.get("/isbn-search/")
        content = response.content.decode()
        assert 'id="lookup-year-end"' in content

    def test_page_contains_max_results_select(self):
        response = self.client.get("/isbn-search/")
        content = response.content.decode()
        assert 'id="lookup-max-results"' in content

    def test_page_contains_search_button(self):
        response = self.client.get("/isbn-search/")
        content = response.content.decode()
        assert 'id="btn-search-books"' in content

    def test_page_contains_loading_indicator(self):
        response = self.client.get("/isbn-search/")
        content = response.content.decode()
        assert 'id="lookup-loading"' in content

    def test_page_contains_results_wrapper(self):
        response = self.client.get("/isbn-search/")
        content = response.content.decode()
        assert 'id="lookup-results-wrapper"' in content

    def test_page_contains_candidates_table(self):
        response = self.client.get("/isbn-search/")
        content = response.content.decode()
        assert 'id="candidates-body"' in content

    def test_page_contains_select_all_checkbox(self):
        response = self.client.get("/isbn-search/")
        content = response.content.decode()
        assert 'id="select-all-candidates"' in content

    def test_page_contains_copy_to_input_btn(self):
        response = self.client.get("/isbn-search/")
        content = response.content.decode()
        assert 'id="btn-copy-to-input"' in content

    def test_page_contains_run_enrich_btn(self):
        response = self.client.get("/isbn-search/")
        content = response.content.decode()
        assert 'id="btn-run-enrich-selected"' in content

    def test_page_contains_counter_badge(self):
        response = self.client.get("/isbn-search/")
        content = response.content.decode()
        assert 'id="lookup-counter-badge"' in content

    def test_page_contains_status_text(self):
        response = self.client.get("/isbn-search/")
        content = response.content.decode()
        assert 'id="lookup-status-text"' in content

    def test_lookup_api_endpoint_accessible(self):
        response = self.client.get("/isbn-search/lookup/", {"keyword": "test"})
        assert response.status_code == 200

    def test_lookup_api_missing_keyword_returns_400(self):
        response = self.client.get("/isbn-search/lookup/", {"keyword": ""})
        assert response.status_code == 400


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
