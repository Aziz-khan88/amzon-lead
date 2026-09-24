from __future__ import annotations

import csv
import json
import logging
import os
import re
import tempfile
import time
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import Iterable

import requests
from django.conf import settings
from django.utils import timezone

from leadfinder.services.ai.classify_book import classify_book
from leadfinder.services.ai.groq_client import GroqJSONClient
from leadfinder.services.amazon.amazon_scraper import fetch_metadata_from_free_apis
from leadfinder.services.amazon.amazon_url_parser import extract_asin, is_amazon_url
from leadfinder.services.books.free_catalogs import (
    crossref_keyword_search,
    internet_archive_keyword_search,
)
from leadfinder.services.books.google_books_provider import GoogleBooksProvider
from leadfinder.services.books.isbn_intelligence import analyze_identifier
from leadfinder.services.books.library_of_congress_provider import search_library_of_congress
from leadfinder.services.books.open_library_provider import search_openlibrary
from leadfinder.services.parallel import map_parallel
from leadfinder.services.pipeline.run_research import guess_title_author
from leadfinder.services.search.base import SearchResultDTO
from leadfinder.services.search.bing_html_provider import BingHTMLSearchProvider
from leadfinder.services.search.ddgs_html_provider import DDGHTMLSearchProvider
from leadfinder.services.search.ddgs_provider import DDGSSearchProvider

logger = logging.getLogger(__name__)

ISBN_RE = re.compile(
    r"(?:ISBN(?:-1[03])?:?\s*)?"
    r"((?:97[89][-\s]?)?(?:\d[-\s]?){9}[\dXx])",
    re.I,
)
ASIN_RE = re.compile(r"\b(B[A-Z0-9]{9})\b", re.I)
CHILDREN_HINTS = {
    "children",
    "childrens",
    "children's",
    "kids",
    "picture book",
    "illustrated",
    "juvenile",
    "storybook",
    "bedtime",
    "early reader",
    "preschool",
}
TRUSTED_SOURCE_SCORE = {
    "open_library": 0.24,
    "google_books": 0.24,
    "library_of_congress": 0.22,
    "crossref": 0.22,
    "amazon": 0.22,
    "internet_archive": 0.18,
    "ddgs": 0.14,
    "ddgs_html": 0.12,
    "bing_html": 0.12,
}


def parse_year(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def keyword_cache_dir(keyword: str) -> Path:
    normalized_keyword = " ".join((keyword or "").casefold().split())
    slug = re.sub(r"[^a-z0-9]+", "-", normalized_keyword).strip("-")
    if len(slug) > 80:
        digest = sha256(normalized_keyword.encode("utf-8")).hexdigest()[:10]
        slug = f"{slug[:69]}-{digest}"
    slug = slug or "keyword"
    return Path(settings.BASE_DIR) / "data" / "isbn_keyword_database" / slug


def year_cache_key(year_start: int | None, year_end: int | None) -> str:
    start = str(year_start) if year_start else "any"
    end = str(year_end) if year_end else "any"
    return f"{start}-{end}"


def cache_paths(keyword: str, year_start: int | None, year_end: int | None) -> dict[str, Path]:
    folder = keyword_cache_dir(keyword)
    key = year_cache_key(year_start, year_end)
    return {
        "folder": folder,
        "json": folder / f"{key}_results.json",
        "csv": folder / f"{key}_isbns.csv",
    }


def year_ok(year_value: str | int | None, year_start: int | None, year_end: int | None) -> bool:
    if year_value in (None, ""):
        return True
    try:
        year = int(str(year_value)[:4])
    except (TypeError, ValueError):
        return True
    if year_start and year < year_start:
        return False
    if year_end and year > year_end:
        return False
    return True


def normalize_book_code(value: str | None) -> str:
    analysis = analyze_identifier(value)
    return analysis.canonical if analysis.valid else ""


def canonical_book_key(value: str | None) -> str:
    """Deduplicate equivalent ISBN-10/ISBN-13 values as one Amazon book."""
    analysis = analyze_identifier(value)
    if not analysis.valid:
        return ""
    return analysis.isbn13 or analysis.canonical


def amazon_identity(value: str | None) -> dict[str, str | bool]:
    """Return a possible ASIN alias without treating it as Amazon evidence.

    An ISBN-10 can be used in an Amazon product URL, but that does not prove that
    a matching product exists. A URL is qualified only when a real Amazon product
    result carries that identifier; callers must make that source check.
    """
    analysis = analyze_identifier(value)
    if not analysis.valid:
        return {"qualified": False, "amazon_asin": "", "evidence": "invalid_identifier"}
    if analysis.identifier_type == "asin":
        return {
            "qualified": False,
            "amazon_asin": analysis.canonical,
            "evidence": "asin_requires_amazon_product_evidence",
        }
    if analysis.isbn10:
        return {
            "qualified": False,
            "amazon_asin": analysis.isbn10,
            "evidence": "isbn10_requires_amazon_product_evidence",
        }
    return {"qualified": False, "amazon_asin": "", "evidence": "no_amazon_asin_mapping"}


def isbn10_is_valid(code: str) -> bool:
    analysis = analyze_identifier(code)
    return analysis.valid and analysis.identifier_type == "isbn10"


def isbn13_is_valid(code: str) -> bool:
    analysis = analyze_identifier(code)
    return analysis.valid and analysis.identifier_type == "isbn13"


def identifier_type(code: str) -> str:
    if re.fullmatch(r"B0[A-Z0-9]{8}", code):
        return "asin"
    if len(code) == 13:
        return "isbn13"
    if len(code) == 10:
        return "isbn10"
    return "unknown"


def extract_isbn_from_text(*parts: str | None) -> str:
    text = " ".join(part or "" for part in parts)
    for match in ISBN_RE.finditer(text):
        code = normalize_book_code(match.group(1))
        if code and not code.startswith("B"):
            return code
    return ""


def extract_asin_from_text(*parts: str | None) -> str:
    text = " ".join(part or "" for part in parts)
    match = ASIN_RE.search(text)
    return normalize_book_code(match.group(1)) if match else ""


def text_has_childrens_signal(*parts: str | None) -> bool:
    text = " ".join(part or "" for part in parts).lower()
    return any(term in text for term in CHILDREN_HINTS)


def has_author(author_name: str | None) -> bool:
    cleaned = (author_name or "").strip().lower()
    return bool(cleaned and cleaned not in {"unknown", "unknown author", "n/a", "none"})


def refine_metadata_with_ai(book: dict) -> dict:
    prompt = (
        "Extract and validate children's book metadata from noisy search evidence. "
        "Return JSON with keys: title, author_name, publication_date, is_valid_book, "
        "confidence, reason. Use null for unknown values. Reject marketplace/category/list pages."
    )
    payload = {
        "title": book.get("title"),
        "author_name": book.get("author_name"),
        "publication_date": book.get("publication_date"),
        "identifier": book.get("asin") or book.get("isbn"),
        "source": book.get("source"),
        "source_url": book.get("source_url"),
        "source_title": book.get("source_title"),
        "source_snippet": book.get("source_snippet"),
    }
    client = GroqJSONClient()
    book["ai_metadata_attempted"] = bool(getattr(client, "available", False))
    ai = client.complete_json(prompt, payload)
    if not ai:
        book["ai_metadata_completed"] = False
        return book
    book["ai_metadata_completed"] = True
    layers = list(book.get("analysis_layers") or [])
    if "groq_ai_metadata_refinement" not in layers:
        layers.append("groq_ai_metadata_refinement")
    book["analysis_layers"] = layers
    book["ai_layer"] = "groq_metadata_refinement"
    if ai.get("is_valid_book") is False:
        book["ai_metadata_rejected"] = True
        book["ai_metadata_reason"] = ai.get("reason") or "AI rejected noisy listing."
        return book
    if ai.get("title"):
        book["title"] = str(ai["title"]).strip()[:500]
    if ai.get("author_name"):
        book["author_name"] = str(ai["author_name"]).strip()[:255]
    if ai.get("publication_date"):
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", str(ai["publication_date"]))
        book["publication_date"] = year_match.group(0) if year_match else str(ai["publication_date"])[:100]
    book["ai_metadata_confidence"] = ai.get("confidence")
    book["ai_metadata_reason"] = ai.get("reason") or ""
    return book


def professional_validation(book: dict, source: str) -> dict:
    layers: list[str] = []
    score = 0.0

    code = str(book.get("asin") or book.get("isbn") or "").upper()
    id_type = identifier_type(code)
    if id_type != "unknown":
        layers.append(f"valid_{id_type}")
        score += 0.28

    if book.get("title"):
        layers.append("title_present")
        score += 0.08
    if book.get("author_name"):
        layers.append("author_present")
        score += 0.08
    if book.get("publication_date"):
        layers.append("publication_date_present")
        score += 0.06
    if book.get("cover_image_url"):
        layers.append("cover_present")
        score += 0.04

    source_score = TRUSTED_SOURCE_SCORE.get(source, 0.1)
    layers.append(f"source_{source}")
    score += source_score

    if book.get("catalog_verified"):
        layers.append("catalog_record_verified")
        score += 0.05
    if int(book.get("metadata_source_count") or 0) >= 2:
        layers.append("multi_source_agreement")
        score += 0.05

    ai_confidence = float(book.get("book_classification_confidence") or 0)
    if book.get("is_childrens_book") is True:
        layers.append("ai_childrens_match")
        score += min(ai_confidence * 0.18, 0.18)
    if book.get("is_picture_or_illustrated_book") is True:
        layers.append("ai_picture_or_illustrated_match")
        score += min(ai_confidence * 0.1, 0.1)
    if text_has_childrens_signal(
        book.get("title"),
        book.get("category"),
        book.get("source_title"),
        book.get("source_snippet"),
    ):
        layers.append("keyword_childrens_signal")
        score += 0.08

    return {
        "identifier_type": id_type,
        "validation_score": round(min(score, 0.99), 3),
        "analysis_layers": layers,
        "analysis_summary": "; ".join(layers),
    }


def cached_book_is_valid(book: dict, year_start: int | None, year_end: int | None) -> bool:
    code = normalize_book_code(str(book.get("asin") or book.get("isbn") or ""))
    if not code:
        return False
    if (year_start or year_end) and not book.get("publication_date"):
        return False
    if not year_ok(book.get("publication_date") or None, year_start, year_end):
        return False
    if not has_author(book.get("author_name")):
        return False
    return True


def load_cached_books(keyword: str, year_start: int | None, year_end: int | None) -> list[dict]:
    json_path = cache_paths(keyword, year_start, year_end)["json"]
    if not json_path.exists():
        return []
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read ISBN keyword cache: %s", json_path)
        return []
    stored_keyword = " ".join(str(payload.get("keyword") or "").casefold().split())
    requested_keyword = " ".join((keyword or "").casefold().split())
    if stored_keyword and stored_keyword != requested_keyword:
        logger.warning("Ignored mismatched ISBN keyword cache at %s", json_path)
        return []
    books = payload.get("books", [])
    if not isinstance(books, list):
        return []
    return [
        book
        for book in books
        if isinstance(book, dict) and cached_book_is_valid(book, year_start, year_end)
    ]


def save_cached_books(
    keyword: str,
    year_start: int | None,
    year_end: int | None,
    books: list[dict],
    queries_run: list[str],
) -> Path:
    paths = cache_paths(keyword, year_start, year_end)
    folder = paths["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    deduped = dedupe_books(books)
    payload = {
        "keyword": keyword,
        "year_start": year_start,
        "year_end": year_end,
        "updated_at": timezone.now().isoformat(),
        "count": len(deduped),
        "queries_run": queries_run,
        "books": deduped,
    }
    _atomic_write_text(paths["json"], json.dumps(payload, indent=2, ensure_ascii=True))
    _write_isbn_csv(paths["csv"], deduped)
    return paths["json"]


def dedupe_books(books: Iterable[dict]) -> list[dict]:
    seen: set[str] = set()
    deduped: list[dict] = []
    for book in books:
        code = normalize_book_code(str(book.get("asin") or book.get("isbn") or "").strip().upper())
        dedupe_key = canonical_book_key(code)
        if not code or not dedupe_key or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        copy = dict(book)
        copy["asin"] = code
        if "isbn" in copy:
            copy["isbn"] = code
        deduped.append(copy)
    return deduped


# Discovery query families. ``{k}`` is the keyword, ``{y}`` an optional
# publication year. The families deliberately attack many different indexes
# (Amazon stores, book catalogs, retailers, review trades, publisher catalogs)
# and many different intents (formats, age bands, self-pub angles) so the same
# keyword keeps surfacing fresh ISBN/ASIN evidence across providers.
_QUERY_TEMPLATES: tuple[str, ...] = (
    # Amazon store angles.
    "site:amazon.com/dp {k} {y} children book",
    "site:amazon.com {k} {y} ISBN",
    "amazon {k} {y} picture book",
    "{k} {y} ISBN amazon",
    "amazon {k} {y} illustrated",
    "{k} {y} book author amazon",
    "amazon {k} {y} paperback",
    "amazon {k} {y} hardcover",
    'site:amazon.com "{k}" "ages 4-8" {y}',
    'site:amazon.com "{k}" "ages 3-5" {y}',
    'site:amazon.com "{k}" "ages 0-3" {y}',
    'site:amazon.com "{k}" "ages 6-9" {y}',
    'site:amazon.com "{k}" "board book" {y}',
    'site:amazon.com "{k}" "kindle edition" kids {y}',
    '"{k}" {y} kindle kids book author',
    # Amazon international stores.
    "site:amazon.co.uk {k} {y} picture book ISBN",
    "site:amazon.ca {k} {y} children book ISBN",
    "site:amazon.com.au {k} {y} picture book ISBN",
    # Book catalog & metadata sites.
    "site:isbnsearch.org {k} {y} children book",
    "site:worldcat.org {k} {y} juvenile ISBN",
    'site:worldcat.org "{k}" {y} picture book',
    "site:goodreads.com {k} {y} ISBN children",
    'site:goodreads.com/book/show "{k}" {y} picture book',
    "site:barnesandnoble.com/w {k} {y} ISBN",
    "site:bookshop.org {k} {y} ISBN children",
    "site:indiebound.org {k} {y} picture book ISBN",
    "site:powells.com {k} {y} children book ISBN",
    "site:booksamillion.com {k} {y} kids book ISBN",
    "site:thriftbooks.com {k} {y} picture book",
    "site:abebooks.com {k} {y} children book ISBN",
    "site:alibris.com {k} {y} picture book ISBN",
    "site:betterworldbooks.com {k} {y} children book",
    "site:waterstones.com {k} {y} picture book ISBN",
    "site:target.com {k} {y} picture book ISBN",
    "site:walmart.com {k} {y} children book ISBN",
    "site:books.google.com {k} {y} juvenile fiction",
    "site:openlibrary.org {k} {y} ISBN juvenile",
    "site:openlibrary.org/books {k} {y} picture book",
    "site:books.apple.com {k} {y} children book",
    "site:kobo.com {k} {y} kids book ISBN",
    # Trade review & discovery sites.
    "site:publishersweekly.com {k} {y} picture book",
    "site:kirkusreviews.com {k} {y} picture book",
    "site:booklife.com {k} {y} children book",
    "site:booklife.com {k} {y} ISBN picture book",
    "site:schoollibraryjournal.com {k} {y} picture book",
    # Publisher catalogs (pages usually carry ISBN + author bylines).
    "site:penguinrandomhouse.com {k} {y} picture book ISBN",
    "site:harpercollins.com {k} {y} children book ISBN",
    "site:simonandschuster.com {k} {y} picture book ISBN",
    "site:hachettebookgroup.com {k} {y} children book ISBN",
    "site:sourcebooks.com {k} {y} children book ISBN",
    # Phrase & intent angles.
    '"{k}" {y} "ISBN-13" picture book',
    '"{k}" {y} "ISBN-10" children book',
    '"{k}" {y} "read aloud" picture book ISBN',
    '"{k}" {y} board book ISBN amazon',
    '"{k}" {y} storytime children book author',
    '"{k}" debut picture book {y} amazon',
    '"{k}" {y} picture book "hardcover" author ISBN',
    '"{k}" {y} self published children book ISBN',
    '"{k}" {y} indie author picture book ISBN',
    '"{k}" {y} "early reader" book ISBN',
    '"{k}" {y} "chapter book" ISBN children',
    '"{k}" {y} bedtime story book ISBN',
    '"{k}" {y} "illustrated by" picture book ISBN',
    '"{k}" {y} juvenile fiction "ISBN-13"',
    '"{k}" {y} children\'s picture book "paperback" ISBN',
    '"{k}" {y} toddler board book amazon',
    '"{k}" {y} preschool picture book author',
    '"{k}" {y} "ages 4-8" picture book ISBN',
    '"{k}" {y} "ages 3-5" children book ISBN',
    '"{k}" {y} "ages 2-6" picture book ISBN',
    '"{k}" {y} read along kids book ISBN',
    # Generic keyword + identifier angles.
    "{k} {y} picture book ISBN author",
    "{k} {y} juvenile fiction ISBN",
    "{k} {y} ASIN picture book author",
    "{k} {y} publisher ISBN children book",
)

# Extra angles that only make sense with a concrete publication year.
_YEAR_ONLY_TEMPLATES: tuple[str, ...] = (
    "{k} published {y} amazon",
    "{k} {y} new release children book amazon",
    '"{k}" {y} "new children\'s books" ISBN',
)


def _render_query(template: str, keyword: str, year: int | None) -> str:
    rendered = template.replace("{k}", keyword).replace("{y}", str(year) if year else "")
    return " ".join(rendered.split())


def build_queries(keyword: str, year_start: int | None, year_end: int | None) -> list[str]:
    years: list[int | None]
    if year_start and year_end:
        years = list(range(year_start, year_end + 1))
    elif year_start:
        years = [year_start]
    elif year_end:
        years = [year_end]
    else:
        years = [None]

    queries: list[str] = []
    for year in years:
        for template in _QUERY_TEMPLATES:
            queries.append(_render_query(template, keyword, year))
        if year:
            for template in _YEAR_ONLY_TEMPLATES:
                queries.append(_render_query(template, keyword, year))
    return list(dict.fromkeys(q for q in queries if q.strip()))


def build_book_record(
    *,
    code: str,
    title: str,
    author_name: str,
    publication_date: str = "",
    cover_image_url: str = "",
    publisher: str = "",
    category: str = "",
    source: str,
    source_url: str = "",
    source_title: str = "",
    source_snippet: str = "",
    book_data_confidence: float = 0.35,
    require_childrens_signal: bool = True,
    require_author: bool = True,
    year_start: int | None = None,
    year_end: int | None = None,
) -> dict | None:
    normalized_code = normalize_book_code(code)
    if not normalized_code or not title:
        return None
    amazon = amazon_identity(normalized_code)
    source_asin = extract_asin(source_url) if is_amazon_url(source_url) else None
    identifier = analyze_identifier(normalized_code)
    amazon_aliases = {
        value for value in (identifier.canonical, identifier.isbn10) if value
    }
    has_direct_amazon_product = bool(source_asin and source_asin in amazon_aliases)
    verified_amazon_url = source_url if has_direct_amazon_product else ""

    try:
        api_data = fetch_metadata_from_free_apis(normalized_code)
    except Exception as exc:
        logger.debug("ISBN keyword metadata enrichment failed for %s: %s", normalized_code, exc)
        api_data = None

    if api_data:
        title = api_data.get("title") or title
        api_authors = api_data.get("authors") or []
        if not author_name and api_authors:
            first_author = api_authors[0]
            author_name = first_author.get("name", "") if isinstance(first_author, dict) else str(first_author)
        publisher = api_data.get("publisher") or publisher
        cover_image_url = api_data.get("cover_image_url") or cover_image_url
        raw_date = str(api_data.get("publication_date") or "")
        if not publication_date and raw_date:
            api_year = re.search(r"\b(19\d{2}|20\d{2})\b", raw_date)
            publication_date = api_year.group(0) if api_year else raw_date[:100]

    metadata_sources = (api_data or {}).get("metadata_sources") or []
    metadata_providers = sorted(
        {
            str(entry.get("provider") or "")
            for entry in metadata_sources
            if isinstance(entry, dict) and entry.get("provider")
        }
    )

    book = {
        "title": title[:500],
        "author_name": (author_name or "").strip()[:255],
        "asin": normalized_code,
        "isbn": normalized_code,
        "amazon_asin": source_asin or "",
        "amazon_book_url": verified_amazon_url,
        "amazon_qualified": has_direct_amazon_product,
        "amazon_qualification_evidence": (
            "direct_amazon_product_url" if has_direct_amazon_product else amazon["evidence"]
        ),
        "publication_date": publication_date[:100],
        "cover_image_url": cover_image_url,
        "publisher": publisher[:255],
        "category": category[:255],
        "source": source,
        "source_url": source_url,
        "source_title": source_title,
        "source_snippet": source_snippet,
        "book_data_confidence": book_data_confidence,
        "catalog_verified": bool(api_data),
        "metadata_confidence": (api_data or {}).get("metadata_confidence") if api_data else None,
        "metadata_source_count": len(metadata_sources),
        "metadata_providers": ", ".join(metadata_providers),
    }
    # Catalog-verified books already carry reconciled titles/authors from
    # trusted sources, so the optional Groq refinement is reserved for
    # web-snippet books where noisy metadata actually needs AI validation.
    # This halves paid-model token use and removes a serial per-book wait.
    if api_data:
        book["ai_metadata_attempted"] = False
        book["ai_metadata_completed"] = False
        book["ai_metadata_skipped"] = "catalog_verified_metadata_trusted"
    else:
        book = refine_metadata_with_ai(book)
    if book.get("ai_metadata_rejected"):
        return None
    if (year_start or year_end) and not book.get("publication_date"):
        return None
    if not year_ok(book.get("publication_date") or None, year_start, year_end):
        return None
    if require_author and not has_author(book.get("author_name")):
        return None

    classification = classify_book(
        book,
        snippets=[source_title, source_snippet, category, publisher],
        use_ai=True,
    )
    book["ai_analysis"] = asdict(classification)
    book["is_childrens_book"] = classification.is_childrens_book
    book["is_picture_or_illustrated_book"] = classification.is_picture_or_illustrated_book
    book["book_classification_confidence"] = classification.confidence
    book["book_classification_reason"] = classification.reason
    book.update(professional_validation(book, source))

    if require_childrens_signal:
        has_signal = text_has_childrens_signal(
            title,
            category,
            publisher,
            source_title,
            source_snippet,
            classification.reason,
        )
        ai_accepts = classification.is_childrens_book is True and classification.confidence >= 0.45
        if not (has_signal or ai_accepts):
            return None
    return book


def _prepare_search_candidate(
    dto: SearchResultDTO,
    source_name: str,
    year_start: int | None,
    year_end: int | None,
) -> dict | None:
    """Cheap, network-free candidate extraction.

    Heavy enrichment (public-catalog reconciliation, AI classification) runs
    later inside ``build_book_record`` so candidates can be enriched in
    parallel worker threads.
    """
    asin = extract_asin(dto.url)
    code = normalize_book_code(asin) if asin and is_amazon_url(dto.url) else ""
    if not code:
        code = extract_isbn_from_text(dto.title, dto.snippet, dto.url)
    if not code:
        code = extract_asin_from_text(dto.title, dto.snippet, dto.url)
    if not code:
        return None

    source_text = f"{dto.title} {dto.snippet or ''}"
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", source_text)
    publication_date = year_match.group(0) if year_match else ""
    if not year_ok(publication_date or None, year_start, year_end):
        return None

    title, author, confidence = guess_title_author(dto.title, dto.snippet or "")
    return {
        "code": code,
        "title": title or dto.title,
        "author_name": author,
        "publication_date": publication_date,
        "source": source_name,
        "source_url": dto.url,
        "source_title": dto.title,
        "source_snippet": dto.snippet or "",
        "book_data_confidence": confidence,
        "year_start": year_start,
        "year_end": year_end,
    }


def candidate_from_search_result(
    dto: SearchResultDTO,
    source_name: str,
    year_start: int | None,
    year_end: int | None,
) -> dict | None:
    prepared = _prepare_search_candidate(dto, source_name, year_start, year_end)
    if not prepared:
        return None
    return build_book_record(**prepared)


def _prepare_catalog_candidate(
    raw: dict,
    source_name: str,
    year_start: int | None = None,
    year_end: int | None = None,
) -> dict | None:
    """Cheap, network-free catalog row normalization (kwargs for build_book_record)."""
    code = normalize_book_code(raw.get("asin") or raw.get("isbn"))
    if not code:
        return None
    raw_date = str(raw.get("publication_date") or "")
    # A present-but-out-of-range date can never be repaired downstream.
    if raw_date and not year_ok(raw_date, year_start, year_end):
        return None
    source_raw = raw.get("source_raw_json") or {}
    source_url = raw.get("source_url") or raw.get("amazon_source_url") or source_raw.get("info_link") or ""
    source_title = raw.get("source_title") or raw.get("amazon_source_title") or raw.get("title") or ""
    source_snippet = raw.get("source_snippet") or raw.get("amazon_source_snippet") or source_raw.get("description") or ""
    return {
        "code": code,
        "title": raw.get("title") or source_title,
        "author_name": raw.get("author_name") or "",
        "publication_date": raw_date,
        "cover_image_url": raw.get("cover_image_url") or "",
        "publisher": raw.get("publisher") or "",
        "category": raw.get("category") or "",
        "source": source_name,
        "source_url": source_url,
        "source_title": source_title,
        "source_snippet": source_snippet,
        "book_data_confidence": float(raw.get("book_data_confidence") or 0.65),
        "require_childrens_signal": False,
        "year_start": year_start,
        "year_end": year_end,
    }


def candidate_from_catalog_result(
    raw: dict,
    source_name: str,
    year_start: int | None = None,
    year_end: int | None = None,
) -> dict | None:
    prepared = _prepare_catalog_candidate(raw, source_name, year_start, year_end)
    if not prepared:
        return None
    return build_book_record(**prepared)


def stream_keyword_lookup(keyword: str, pub_year_start: str, pub_year_end: str, max_results: int, only_new: bool = False):
    year_start = parse_year(pub_year_start)
    year_end = parse_year(pub_year_end)
    cached_books = load_cached_books(keyword, year_start, year_end)
    all_books = dedupe_books(cached_books)
    seen_ids = {
        canonical_book_key(str(book.get("asin") or book.get("isbn") or ""))
        for book in all_books
    }
    seen_ids.discard("")
    books_yielded = 0
    queries_run: list[str] = []
    workers = max(1, int(getattr(settings, "APP_ISBN_LOOKUP_WORKERS", 8) or 8))

    yield {
        "status": "starting",
        "message": f"Checking saved keyword folder before parallel public search ({workers} workers)...",
        "cache_path": str(cache_paths(keyword, year_start, year_end)["folder"]),
    }

    if not only_new and all_books:
        cached_slice = all_books[:max_results]
        books_yielded = len(cached_slice)
        yield {
            "status": "progress",
            "message": f"Loaded {books_yielded} saved books for this keyword.",
            "books": cached_slice,
            "count": books_yielded,
            "cache_hit": True,
        }

    if not only_new and books_yielded >= max_results:
        yield {
            "status": "done",
            "count": books_yielded,
            "cache_hit": True,
            "cache_path": str(cache_paths(keyword, year_start, year_end)["json"]),
        }
        return

    def _select_pending(prepared: Iterable[dict | None], remaining: int) -> list[dict]:
        """Dedupe against seen ids and cap selection in the calling thread."""
        selected: list[dict] = []
        for candidate_kwargs in prepared:
            if not candidate_kwargs:
                continue
            if len(selected) >= remaining:
                break
            code = str(candidate_kwargs.get("code") or "").upper()
            dedupe_key = canonical_book_key(code)
            if not code or not dedupe_key or dedupe_key in seen_ids:
                continue
            seen_ids.add(dedupe_key)
            selected.append(candidate_kwargs)
        return selected

    def _build_candidate(candidate_kwargs: dict) -> dict | None:
        """Network-bound enrichment worker; never raises into the pool."""
        try:
            return build_book_record(**candidate_kwargs)
        except Exception as exc:
            logger.debug("Book record build failed for %s: %s", candidate_kwargs.get("code"), exc)
            return None

    def _commit_batch(batch: list[dict]) -> Path:
        nonlocal books_yielded
        all_books.extend(batch)
        if only_new:
            books_yielded += len(batch)
        else:
            books_yielded = min(len(all_books), max_results)
        return save_cached_books(keyword, year_start, year_end, all_books, queries_run)

    def _enrich_and_commit(prepared: Iterable[dict | None], remaining: int) -> list[dict] | None:
        """Select, enrich in parallel, commit, and return the saved batch."""
        if remaining <= 0:
            return None
        selected = _select_pending(prepared, remaining)
        if not selected:
            return None
        built = map_parallel(_build_candidate, selected, max_workers=workers)
        batch = [book for book in built if book]
        if not batch:
            return None
        _commit_batch(batch)
        return batch

    queries = build_queries(keyword, year_start, year_end)
    # The query families are much larger now; keep the floor high enough that
    # even small hunts sample a diverse slice of them before giving up.
    deep_query_limit = int(getattr(settings, "APP_ISBN_LOOKUP_DEEP_QUERY_LIMIT", max(48, min(len(queries), max_results))))
    queries = queries[: max(1, min(len(queries), deep_query_limit))]
    providers = [
        ("ddgs", DDGSSearchProvider(), 30),
        ("ddgs_html", DDGHTMLSearchProvider(delay=0.4), 30),
        ("bing_html", BingHTMLSearchProvider(delay=0.4), 30),
    ]
    search_tasks = [
        (provider_name, provider, query, result_limit)
        for provider_name, provider, result_limit in providers
        for query in queries
    ]
    total_steps = len(search_tasks)
    # Web snippets are useful for Amazon URL discovery, but they must not crowd
    # authoritative catalogs out of the result budget on normal-sized runs.
    catalog_reserve = max(1, round(max_results * 0.4)) if max_results >= 5 else 0
    web_result_cap = max_results - catalog_reserve

    def _run_search_task(task) -> tuple[str, str, list]:
        provider_name, provider, query, result_limit = task
        try:
            return provider_name, query, provider.search(query, max_results=result_limit) or []
        except Exception as exc:
            logger.warning("%s ISBN keyword query failed for %r: %s", provider_name, query, exc)
            return provider_name, query, []

    # Web search layers (2-4/10) run concurrently in chunks: each chunk's
    # queries are searched in parallel, then new candidates are enriched in
    # parallel and saved before the next chunk starts.
    chunk_size = max(4, workers * 2)
    for chunk_start in range(0, len(search_tasks), chunk_size):
        if books_yielded >= web_result_cap:
            break
        chunk = search_tasks[chunk_start:chunk_start + chunk_size]
        queries_run.extend(f"{name}: {query}" for name, _, query, _ in chunk)
        yield {
            "status": "searching",
            "message": (
                f"[{min(chunk_start + len(chunk), total_steps)}/{total_steps}] "
                f"Layers 2-4/10: parallel web scan ({workers} workers): {chunk[0][2]}"
            ),
            "count": books_yielded,
            "cache_hit": bool(cached_books),
        }
        outcomes = map_parallel(_run_search_task, chunk, max_workers=workers)
        prepared = (
            _prepare_search_candidate(dto, provider_name, year_start, year_end)
            for provider_name, _query, results in outcomes
            for dto in results
        )
        batch = _enrich_and_commit(prepared, web_result_cap - books_yielded)
        if batch:
            yield {
                "status": "progress",
                "message": f"Saved {len(batch)} new books to keyword folder.",
                "books": batch,
                "count": books_yielded,
                "cache_updated": True,
                "cache_path": str(cache_paths(keyword, year_start, year_end)["json"]),
            }
        time.sleep(0.1)

    def _fetch_catalog(task) -> tuple[str, list, str]:
        """Catalog fetch worker; provider failures degrade to empty results."""
        name, fetcher = task
        try:
            return name, fetcher() or [], ""
        except Exception as exc:
            logger.warning("%s ISBN keyword lookup failed: %s", name, exc)
            return name, [], str(exc)

    def _run_catalog_phase(tasks_with_meta) -> Iterable[dict]:
        """Fetch catalog layers concurrently, then commit them in trust order."""
        nonlocal books_yielded
        outcomes = map_parallel(_fetch_catalog, [(name, fetcher) for name, fetcher, _label, _layer in tasks_with_meta], max_workers=len(tasks_with_meta))
        for (name, raw_results, _error), (_name, _fetcher, label, layer_label) in zip(outcomes, tasks_with_meta):
            if books_yielded >= max_results:
                break
            queries_run.append(f"{name}: {keyword}")
            yield {
                "status": "searching",
                "message": f"{layer_label}: {label} lookup for: {keyword}",
                "count": books_yielded,
                "cache_hit": bool(cached_books),
            }
            if not raw_results:
                continue
            prepared = (
                _prepare_catalog_candidate(raw, name, year_start, year_end)
                for raw in raw_results
            )
            batch = _enrich_and_commit(prepared, max_results - books_yielded)
            if batch:
                yield {
                    "status": "progress",
                    "message": f"Saved {len(batch)} new books from {label} to keyword folder.",
                    "books": batch,
                    "count": books_yielded,
                    "cache_updated": True,
                    "cache_path": str(cache_paths(keyword, year_start, year_end)["json"]),
                }

    # Trusted catalog layers (5-7/10): Google Books, Open Library, and the
    # Library of Congress are fetched concurrently, then committed in order.
    if books_yielded < max_results:
        remaining = max_results - books_yielded
        gb = GoogleBooksProvider()
        yield {
            "status": "searching",
            "message": "Layers 5-7/10: querying Google Books, Open Library, and the Library of Congress in parallel...",
            "count": books_yielded,
            "cache_hit": bool(cached_books),
        }
        yield from _run_catalog_phase(
            [
                (
                    "google_books",
                    lambda: gb.discover_books(
                        keyword,
                        max_books=remaining,
                        order_by="newest" if (year_start or year_end) else "relevance",
                    ),
                    "Google Books API",
                    "Layer 5/10",
                ),
                (
                    "open_library",
                    lambda: search_openlibrary(
                        keyword,
                        year_start=year_start,
                        year_end=year_end,
                        max_books=remaining,
                        sort_new=bool(year_start or year_end),
                    ),
                    "Open Library API",
                    "Layer 6/10",
                ),
                (
                    "library_of_congress",
                    lambda: search_library_of_congress(
                        keyword,
                        year_start=year_start,
                        year_end=year_end,
                        max_books=remaining,
                    ),
                    "Library of Congress",
                    "Layer 7/10",
                ),
            ]
        )

    # Extra free, no-key harvest layers (8-9/10): Crossref publisher deposits
    # (freshest metadata) and the Internet Archive scanned-book catalog. These
    # only run while budget remains so polite fallbacks stay bounded.
    extra_catalogs_enabled = bool(getattr(settings, "APP_ISBN_LOOKUP_EXTRA_CATALOGS", True))
    if extra_catalogs_enabled and books_yielded < max_results:
        remaining = max_results - books_yielded
        yield {
            "status": "searching",
            "message": "Layers 8-9/10: harvesting Crossref and Internet Archive catalogs in parallel...",
            "count": books_yielded,
            "cache_hit": bool(cached_books),
        }
        yield from _run_catalog_phase(
            [
                (
                    "crossref",
                    lambda: crossref_keyword_search(
                        requests.Session(),
                        keyword,
                        year_start=year_start,
                        year_end=year_end,
                        max_books=remaining,
                    ),
                    "Crossref",
                    "Layer 8/10",
                ),
                (
                    "internet_archive",
                    lambda: internet_archive_keyword_search(
                        requests.Session(),
                        keyword,
                        year_start=year_start,
                        year_end=year_end,
                        max_books=remaining,
                    ),
                    "Internet Archive",
                    "Layer 9/10",
                ),
            ]
        )

    if all_books:
        ai_completed = sum(1 for book in all_books if book.get("ai_metadata_completed"))
        ai_attempted = any(book.get("ai_metadata_attempted") for book in all_books)
        yield {
            "status": "searching",
            "message": (
                f"Layer 10/10: Groq metadata refinement completed for {ai_completed} books."
                if ai_attempted
                else "Layer 10/10: Optional Groq refinement unavailable; deterministic validation retained."
            ),
            "count": books_yielded,
            "cache_hit": bool(cached_books),
        }

    cache_path = save_cached_books(keyword, year_start, year_end, all_books, queries_run)
    yield {
        "status": "done",
        "count": min(books_yielded, max_results),
        "cache_updated": True,
        "cache_path": str(cache_path),
    }


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, newline="") as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def _write_isbn_csv(path: Path, books: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, newline="") as tmp:
        writer = csv.DictWriter(
            tmp,
            fieldnames=[
                "asin",
                "isbn",
                "title",
                "author_name",
                "publication_date",
                "amazon_book_url",
                "amazon_asin",
                "amazon_qualified",
                "amazon_qualification_evidence",
                "source",
                "identifier_type",
                "validation_score",
                "analysis_summary",
                "catalog_verified",
                "metadata_confidence",
                "metadata_source_count",
                "metadata_providers",
                "ai_layer",
                "ai_metadata_confidence",
                "ai_metadata_reason",
                "book_classification_confidence",
                "is_childrens_book",
                "is_picture_or_illustrated_book",
            ],
        )
        writer.writeheader()
        for book in books:
            writer.writerow({field: book.get(field, "") for field in writer.fieldnames})
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)
