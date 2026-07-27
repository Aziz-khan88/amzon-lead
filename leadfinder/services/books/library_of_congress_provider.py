"""No-key Library of Congress book discovery.

The LOC JSON API is used as a bounded fallback, not as a bulk crawler. Responses
are cached through Django and only checksum-valid ISBN records are returned.
"""

from __future__ import annotations

import logging
import re
from hashlib import sha256
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache

from leadfinder.services.books.isbn_intelligence import analyze_identifier

logger = logging.getLogger(__name__)

LOC_BOOKS_ENDPOINT = "https://www.loc.gov/books/"
USER_AGENT = "BookTrailerLeadFinder/1.0 (public catalog discovery)"


def _values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value in (None, ""):
        return []
    return [str(value).strip()]


def _isbn_candidates(item: dict[str, Any]) -> list[str]:
    raw_values: list[str] = []
    for field in ("number_isbn", "isbn"):
        raw_values.extend(_values(item.get(field)))
    number = item.get("number") or []
    for entry in number if isinstance(number, list) else [number]:
        if isinstance(entry, dict) and str(entry.get("type", "")).lower() == "isbn":
            raw_values.extend(_values(entry.get("value")))

    candidates: list[str] = []
    for raw in raw_values:
        # LOC values may include binding notes after the identifier.
        candidates.extend(re.findall(r"(?:97[89][ -]?)?(?:\d[ -]?){9}[\dXx]", raw))
    return candidates


def _best_isbn(item: dict[str, Any]) -> str:
    analyses = [analyze_identifier(value) for value in _isbn_candidates(item)]
    valid = [entry for entry in analyses if entry.valid and entry.identifier_type in {"isbn10", "isbn13"}]
    if not valid:
        return ""
    return next((entry.isbn13 for entry in valid if entry.isbn13), "") or valid[0].canonical


def _publication_year(item: dict[str, Any]) -> str:
    for value in _values(item.get("date")) + _values(item.get("dates")):
        match = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", value)
        if match:
            return match.group(0)
    return ""


def _year_matches(year: str, year_start: int | None, year_end: int | None) -> bool:
    if not year:
        return not (year_start or year_end)
    numeric = int(year)
    return (not year_start or numeric >= year_start) and (not year_end or numeric <= year_end)


def _candidate(item: dict[str, Any], year_start: int | None, year_end: int | None) -> dict | None:
    isbn = _best_isbn(item)
    title = str(item.get("title") or "").strip()
    contributors = _values(item.get("contributor")) or _values(item.get("creator"))
    year = _publication_year(item)
    if not isbn or not title or not contributors or not _year_matches(year, year_start, year_end):
        return None

    images = _values(item.get("image"))
    subjects = _values(item.get("subject"))
    publishers = _values(item.get("publisher"))
    source_url = str(item.get("id") or item.get("url") or LOC_BOOKS_ENDPOINT)
    return {
        "title": title,
        "author_name": contributors[0],
        "asin": isbn,
        "isbn": isbn,
        "publication_date": year,
        "cover_image_url": images[-1] if images else "",
        "publisher": publishers[0] if publishers else "",
        "category": "; ".join(subjects[:5]),
        "source": "library_of_congress",
        "source_url": source_url,
        "source_title": title,
        "book_data_confidence": 0.72,
    }


def search_library_of_congress(
    keyword: str,
    year_start: int | None = None,
    year_end: int | None = None,
    max_books: int = 25,
    *,
    session: requests.Session | None = None,
) -> list[dict]:
    """Return unique, ISBN-bearing LOC books for a keyword.

    At most five pages are requested and each query page is cached for 24 hours.
    Provider failures return the results collected so far so later fallbacks can run.
    """
    cleaned = " ".join((keyword or "").split())
    if not cleaned or max_books <= 0:
        return []

    http = session or requests.Session()
    results: list[dict] = []
    seen: set[str] = set()
    page_size = min(100, max(25, max_books * 2))
    max_pages = min(5, max(1, (max_books + page_size - 1) // page_size + 1))

    for page in range(1, max_pages + 1):
        query_digest = sha256(cleaned.lower().encode("utf-8")).hexdigest()[:24]
        cache_key = f"loc-books:v1:{query_digest}:{page}:{page_size}"
        payload = cache.get(cache_key)
        if not isinstance(payload, dict):
            try:
                response = http.get(
                    LOC_BOOKS_ENDPOINT,
                    params={"q": cleaned, "fo": "json", "sp": page, "c": page_size},
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                    timeout=getattr(settings, "APP_REQUEST_TIMEOUT_SECONDS", 15),
                )
                response.raise_for_status()
                raw_payload = response.json()
                payload = raw_payload if isinstance(raw_payload, dict) else {}
                cache.set(cache_key, payload, timeout=60 * 60 * 24)
            except (requests.RequestException, ValueError) as exc:
                logger.warning("Library of Congress query failed for %r: %s", cleaned, exc)
                break

        items = payload.get("results", []) or []
        if not isinstance(items, list) or not items:
            break
        for item in items:
            if not isinstance(item, dict):
                continue
            candidate = _candidate(item, year_start, year_end)
            if not candidate:
                continue
            analysis = analyze_identifier(candidate["isbn"])
            key = analysis.isbn13 or analysis.canonical
            if key in seen:
                continue
            seen.add(key)
            results.append(candidate)
            if len(results) >= max_books:
                return results
        if len(items) < page_size:
            break

    return results
