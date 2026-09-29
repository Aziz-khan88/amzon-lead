"""Additional 100% free, no-API-key ISBN catalog sources.

Three public services complement the Open Library / Google Books pair already
used by ``isbn_intelligence.resolve_free_metadata``:

- **Crossref** (api.crossref.org) — publisher-deposited metadata, often live
  the week a book is published, which makes it the freshest free source.
- **Internet Archive** (archive.org) — scanned-book catalog with covers.
- **Wikidata** (query.wikidata.org) — community-maintained book entities keyed
  by ISBN-10 (P957) / ISBN-13 (P212).

All three are free, need no API key, and ask only for a descriptive
User-Agent.  Each fetcher returns the same record shape as the existing
``_open_library_record`` / ``_google_books_record`` helpers, or ``None`` when
the ISBN has no exact match.  Strict response-shape checks keep unexpected
payloads (rate-limit pages, proxies, test doubles) from becoming fake books.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from xml.etree import ElementTree

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

USER_AGENT = "BookTrailerLeadFinder/1.0 (public book metadata reconciliation)"
_TAG_RE = re.compile(r"<[^>]+>")


def _timeout() -> int:
    return int(getattr(settings, "APP_REQUEST_TIMEOUT_SECONDS", 15))


def _get_json(session: requests.Session, url: str, *, params: dict[str, Any], accept: str = "application/json") -> dict[str, Any]:
    response = session.get(
        url,
        params=params,
        timeout=_timeout(),
        headers={"User-Agent": USER_AGENT, "Accept": accept},
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _clean_html(value: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", value or "")).strip()


# ---------------------------------------------------------------------------
# Crossref — freshest free source (publisher deposits at publication time)
# ---------------------------------------------------------------------------

def crossref_isbn_record(session: requests.Session, isbn: str) -> dict[str, Any] | None:
    payload = _get_json(
        session,
        "https://api.crossref.org/works",
        params={
            "filter": f"isbn:{isbn}",
            "rows": 3,
            "select": "DOI,title,author,publisher,published,ISBN,URL,abstract,type",
        },
    )
    message = payload.get("message")
    if not isinstance(message, dict):
        return None
    items = message.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        isbns = {re.sub(r"\D", "", str(value)) for value in item.get("ISBN") or []}
        if isbns and isbn not in isbns:
            continue
        titles = item.get("title") or []
        title = str(titles[0]).strip() if titles else ""
        if not title:
            continue
        authors = []
        for entry in item.get("author") or []:
            if not isinstance(entry, dict):
                continue
            name = " ".join(
                part for part in (str(entry.get("given") or ""), str(entry.get("family") or "")) if part
            ).strip() or str(entry.get("name") or "").strip()
            if name:
                authors.append(name)
        date_parts = ((item.get("published") or {}).get("date-parts") or [[None]])[0]
        year = str(date_parts[0]) if date_parts and date_parts[0] else ""
        doi = str(item.get("DOI") or "")
        return {
            "provider": "crossref",
            "source_url": str(item.get("URL") or (f"https://doi.org/{doi}" if doi else "https://api.crossref.org")),
            "title": title,
            "authors": authors,
            "publisher": str(item.get("publisher") or "").strip(),
            "publication_date": year,
            "cover_image_url": "",
            "description": _clean_html(str(item.get("abstract") or ""))[:1000],
        }
    return None


# ---------------------------------------------------------------------------
# Internet Archive — scanned catalog with free cover images
# ---------------------------------------------------------------------------

def internet_archive_isbn_record(session: requests.Session, isbn: str) -> dict[str, Any] | None:
    payload = _get_json(
        session,
        "https://archive.org/advancedsearch.php",
        params={
            "q": f"isbn:{isbn} AND mediatype:texts",
            "fl[]": ["identifier", "title", "creator", "date", "publisher", "description"],
            "rows": 5,
            "output": "json",
        },
    )
    response_block = payload.get("response")
    if not isinstance(response_block, dict):
        return None
    docs = response_block.get("docs")
    if not isinstance(docs, list):
        return None

    def _first(value: Any) -> str:
        if isinstance(value, list):
            return str(value[0]).strip() if value else ""
        return str(value or "").strip()

    for doc in docs:
        if not isinstance(doc, dict):
            continue
        title = _first(doc.get("title"))
        identifier = _first(doc.get("identifier"))
        if not title or not identifier:
            continue
        creators = doc.get("creator") or []
        authors = (
            [str(name).strip() for name in creators if str(name).strip()]
            if isinstance(creators, list)
            else ([_first(creators)] if _first(creators) else [])
        )
        year_match = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", _first(doc.get("date")))
        return {
            "provider": "internet_archive",
            "source_url": f"https://archive.org/details/{identifier}",
            "title": title,
            "authors": authors,
            "publisher": _first(doc.get("publisher")),
            "publication_date": year_match.group(0) if year_match else "",
            "cover_image_url": f"https://archive.org/services/img/{identifier}",
            "description": _clean_html(_first(doc.get("description")))[:1000],
        }
    return None


# ---------------------------------------------------------------------------
# Wikidata — community book entities keyed by ISBN-13 (P212) / ISBN-10 (P957)
# ---------------------------------------------------------------------------

_WIKIDATA_SPARQL = """
SELECT ?item ?itemLabel ?title ?authorLabel ?publisherLabel ?date WHERE {
  VALUES ?isbnProp { wdt:P212 wdt:P957 }
  ?item ?isbnProp "%(isbn)s".
  OPTIONAL { ?item wdt:P1476 ?title. }
  OPTIONAL { ?item wdt:P50 ?author. }
  OPTIONAL { ?item wdt:P123 ?publisher. }
  OPTIONAL { ?item wdt:P577 ?date. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""


def wikidata_isbn_record(session: requests.Session, isbn: str) -> dict[str, Any] | None:
    payload = _get_json(
        session,
        "https://query.wikidata.org/sparql",
        params={"query": _WIKIDATA_SPARQL % {"isbn": isbn}, "format": "json"},
        accept="application/sparql-results+json",
    )
    results = payload.get("results")
    if not isinstance(results, dict):
        return None
    bindings = results.get("bindings")
    if not isinstance(bindings, list) or not bindings:
        return None

    def _value(row: dict[str, Any], key: str) -> str:
        entry = row.get(key)
        return str(entry.get("value") or "").strip() if isinstance(entry, dict) else ""

    title = ""
    item_url = ""
    date = ""
    publisher = ""
    authors: list[str] = []
    for row in bindings:
        if not isinstance(row, dict):
            continue
        item_url = item_url or _value(row, "item")
        title = title or _value(row, "title") or _value(row, "itemLabel")
        publisher = publisher or _value(row, "publisherLabel")
        date = date or _value(row, "date")
        author = _value(row, "authorLabel")
        # Skip unresolved entity IDs ("Q12345") that labels leave behind.
        if author and not re.fullmatch(r"Q\d+", author) and author not in authors:
            authors.append(author)
    if not title or re.fullmatch(r"Q\d+", title):
        return None
    year_match = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", date)
    return {
        "provider": "wikidata",
        "source_url": item_url or "https://www.wikidata.org",
        "title": title,
        "authors": authors,
        "publisher": publisher,
        "publication_date": year_match.group(0) if year_match else "",
        "cover_image_url": "",
        "description": "",
    }


# ---------------------------------------------------------------------------
# Keyword discovery (not exact-ISBN): bulk candidate harvesting for the
# instant lookup stream. Both services are free and need no API key.
# Rows use the ``candidate_from_catalog_result`` shape; checksum validation
# happens downstream, so raw ISBN strings are passed through untouched.
# ---------------------------------------------------------------------------

def _year_in_range(year: str, year_start: int | None, year_end: int | None) -> bool:
    if not year:
        return not (year_start or year_end)
    try:
        numeric = int(year)
    except (TypeError, ValueError):
        return False
    return (not year_start or numeric >= year_start) and (not year_end or numeric <= year_end)


def crossref_keyword_search(
    session: requests.Session,
    keyword: str,
    year_start: int | None = None,
    year_end: int | None = None,
    max_books: int = 25,
) -> list[dict[str, Any]]:
    """Bulk-harvest ISBN-bearing books from publisher-deposited Crossref metadata.

    Crossref is the freshest free catalog: publishers deposit metadata the week
    a book is published. One row is emitted per candidate ISBN so downstream
    checksum validation and ISBN-10/13 dedupe can collapse editions.
    """
    cleaned = " ".join((keyword or "").split())
    if not cleaned or max_books <= 0:
        return []
    filters = ["type:book"]
    if year_start:
        filters.append(f"from-pub-date:{year_start}-01-01")
    if year_end:
        filters.append(f"until-pub-date:{year_end}-12-31")
    payload = _get_json(
        session,
        "https://api.crossref.org/works",
        params={
            "query.bibliographic": cleaned,
            "filter": ",".join(filters),
            "rows": min(100, max(20, max_books * 2)),
            "select": "DOI,title,author,publisher,published,ISBN,URL,type",
        },
    )
    message = payload.get("message")
    if not isinstance(message, dict):
        return []
    items = message.get("items")
    if not isinstance(items, list):
        return []

    results: list[dict[str, Any]] = []
    for item in items:
        if len(results) >= max_books:
            break
        if not isinstance(item, dict):
            continue
        titles = item.get("title") or []
        title = str(titles[0]).strip() if titles else ""
        raw_isbns = [re.sub(r"[^0-9Xx]", "", str(value)) for value in item.get("ISBN") or []]
        raw_isbns = [value for value in raw_isbns if len(value) in {10, 13}]
        if not title or not raw_isbns:
            continue
        authors = []
        for entry in item.get("author") or []:
            if not isinstance(entry, dict):
                continue
            name = " ".join(
                part for part in (str(entry.get("given") or ""), str(entry.get("family") or "")) if part
            ).strip() or str(entry.get("name") or "").strip()
            if name:
                authors.append(name)
        date_parts = ((item.get("published") or {}).get("date-parts") or [[None]])[0]
        year = str(date_parts[0]) if date_parts and date_parts[0] else ""
        if not _year_in_range(year, year_start, year_end):
            continue
        doi = str(item.get("DOI") or "")
        source_url = str(item.get("URL") or (f"https://doi.org/{doi}" if doi else "https://api.crossref.org"))
        for isbn in raw_isbns:
            if len(results) >= max_books:
                break
            results.append(
                {
                    "title": title,
                    "author_name": authors[0] if authors else "",
                    "isbn": isbn,
                    "publication_date": year,
                    "publisher": str(item.get("publisher") or "").strip(),
                    "cover_image_url": "",
                    "source": "crossref",
                    "source_url": source_url,
                    "source_title": title,
                    "source_snippet": "",
                    "book_data_confidence": 0.66,
                }
            )
    return results


def internet_archive_keyword_search(
    session: requests.Session,
    keyword: str,
    year_start: int | None = None,
    year_end: int | None = None,
    max_books: int = 25,
) -> list[dict[str, Any]]:
    """Bulk-harvest ISBN-bearing scanned books from the Internet Archive catalog."""
    cleaned = " ".join((keyword or "").split())
    if not cleaned or max_books <= 0:
        return []
    payload = _get_json(
        session,
        "https://archive.org/advancedsearch.php",
        params={
            "q": f"({cleaned}) AND mediatype:texts",
            "fl[]": ["identifier", "title", "creator", "date", "publisher", "isbn"],
            "rows": min(100, max(25, max_books * 2)),
            "output": "json",
        },
    )
    response_block = payload.get("response")
    if not isinstance(response_block, dict):
        return []
    docs = response_block.get("docs")
    if not isinstance(docs, list):
        return []

    def _first(value: Any) -> str:
        if isinstance(value, list):
            return str(value[0]).strip() if value else ""
        return str(value or "").strip()

    def _list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [_first(value)] if _first(value) else []

    results: list[dict[str, Any]] = []
    for doc in docs:
        if len(results) >= max_books:
            break
        if not isinstance(doc, dict):
            continue
        title = _first(doc.get("title"))
        identifier = _first(doc.get("identifier"))
        raw_isbns = [
            re.sub(r"[^0-9Xx]", "", value)
            for value in _list(doc.get("isbn"))
        ]
        raw_isbns = [value for value in raw_isbns if len(value) in {10, 13}]
        if not title or not identifier or not raw_isbns:
            continue
        creators = _list(doc.get("creator"))
        year_match = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", _first(doc.get("date")))
        year = year_match.group(0) if year_match else ""
        if not _year_in_range(year, year_start, year_end):
            continue
        publisher = _first(doc.get("publisher"))
        for isbn in raw_isbns:
            if len(results) >= max_books:
                break
            results.append(
                {
                    "title": title,
                    "author_name": creators[0] if creators else "",
                    "isbn": isbn,
                    "publication_date": year,
                    "publisher": publisher,
                    "cover_image_url": f"https://archive.org/services/img/{identifier}",
                    "source": "internet_archive",
                    "source_url": f"https://archive.org/details/{identifier}",
                    "source_title": title,
                    "source_snippet": "",
                    "book_data_confidence": 0.6,
                }
            )
    return results
