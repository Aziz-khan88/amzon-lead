"""
Open Library ISBN Discovery Provider — Fixed version.
Key fix: do NOT pass publish_year param (breaks API), search broadly
and filter results client-side by year range.
"""
from __future__ import annotations

import logging
import os
import time
from hashlib import sha256
from typing import Generator

import requests
from django.core.cache import cache

from leadfinder.services.books.isbn_intelligence import analyze_identifier

logger = logging.getLogger(__name__)

_BASE_URL = "https://openlibrary.org/search.json"
_COVER_URL = "https://covers.openlibrary.org/b/id/{cover_id}-M.jpg"


def _user_agent() -> str:
    contact = (os.getenv("BOOKTRAILER_CONTACT_EMAIL") or "").strip()
    suffix = f"; mailto:{contact}" if contact else ""
    return f"BookTrailerLeadFinder/1.0 ({suffix.lstrip('; ') or 'public catalog reconciliation'})"


def search_openlibrary(
    keyword: str,
    year_start: int | None = None,
    year_end: int | None = None,
    max_books: int = 50,
    delay: float = 1.05,
) -> list[dict]:
    """
    Search Open Library for books matching keyword + optional year range.
    NOTE: publish_year API param returns 0 results for most queries.
          We search without year filter and filter client-side.
    """
    results: list[dict] = []
    seen_isbns: set[str] = set()
    page = 1
    per_page = 100  # max allowed

    # How many raw pages to fetch before giving up
    max_pages = min(5, max(3, (max_books // 20) + 2))

    while len(results) < max_books and page <= max_pages:
        params: dict = {
            "q": keyword,
            "limit": per_page,
            "page": page,
            "fields": "title,author_name,isbn,first_publish_year,publish_year,cover_i,key",
        }

        digest = sha256(f"{keyword.casefold()}:{page}:{per_page}".encode("utf-8")).hexdigest()[:24]
        cache_key = f"open-library-search:v1:{digest}"
        data = cache.get(cache_key)
        if not isinstance(data, dict):
            try:
                time.sleep(max(delay, 1.0))
                resp = requests.get(
                    _BASE_URL,
                    params=params,
                    headers={"User-Agent": _user_agent(), "Accept": "application/json"},
                    timeout=15,
                )
                resp.raise_for_status()
                payload = resp.json()
                data = payload if isinstance(payload, dict) else {}
                cache.set(cache_key, data, timeout=60 * 60 * 24)
            except Exception as e:
                logger.warning("Open Library request failed: %s", e)
                break

        docs = data.get("docs", [])
        if not docs:
            break

        for doc in docs:
            if len(results) >= max_books:
                break

            raw_isbns = doc.get("isbn") or []
            if not raw_isbns:
                continue

            # Keep only checksum-valid ISBNs; prefer the canonical ISBN-13 form.
            identifiers = [analyze_identifier(str(value)) for value in raw_isbns]
            valid_identifiers = [item for item in identifiers if item.valid and item.identifier_type in {"isbn10", "isbn13"}]
            if not valid_identifiers:
                continue
            best_isbn = next((item.isbn13 for item in valid_identifiers if item.isbn13), "") or valid_identifiers[0].canonical

            if best_isbn in seen_isbns:
                continue

            # Collect all publish years for this book
            pub_years_raw = doc.get("publish_year") or []
            first_year = doc.get("first_publish_year")
            all_years: set[int] = set()
            for y in pub_years_raw:
                try:
                    all_years.add(int(y))
                except (TypeError, ValueError):
                    pass
            if first_year:
                try:
                    all_years.add(int(first_year))
                except (TypeError, ValueError):
                    pass

            # Year range filter (client-side)
            if year_start or year_end:
                yr_s = year_start or 0
                yr_e = year_end or 9999
                in_range = [y for y in all_years if yr_s <= y <= yr_e]
                if not in_range:
                    continue
                display_year = str(max(in_range))
            else:
                display_year = str(max(all_years)) if all_years else ""

            # Cover image
            cover_id = doc.get("cover_i")
            cover_url = _COVER_URL.format(cover_id=cover_id) if cover_id else ""

            authors = doc.get("author_name") or []
            author = authors[0] if authors else "Unknown Author"

            seen_isbns.add(best_isbn)
            results.append({
                "title": doc.get("title", ""),
                "author_name": author,
                "asin": best_isbn,
                "isbn": best_isbn,
                "publication_date": display_year,
                "cover_image_url": cover_url,
                "source": "open_library",
            })

        if len(docs) < per_page:
            break
        page += 1

    return results[:max_books]
