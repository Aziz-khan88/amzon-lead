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

from django.conf import settings
from django.utils import timezone

from leadfinder.services.ai.classify_book import classify_book
from leadfinder.services.ai.groq_client import GroqJSONClient
from leadfinder.services.amazon.amazon_scraper import fetch_metadata_from_free_apis
from leadfinder.services.amazon.amazon_url_parser import extract_asin, is_amazon_url
from leadfinder.services.books.google_books_provider import GoogleBooksProvider
from leadfinder.services.books.isbn_intelligence import analyze_identifier
from leadfinder.services.books.library_of_congress_provider import search_library_of_congress
from leadfinder.services.books.open_library_provider import search_openlibrary
from leadfinder.services.pipeline.run_research import guess_title_author
from leadfinder.services.search.base import SearchResultDTO
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
    "amazon": 0.22,
    "ddgs": 0.14,
    "ddgs_html": 0.12,
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


def build_queries(keyword: str, year_start: int | None, year_end: int | None) -> list[str]:
    years: list[int] = []
    if year_start and year_end:
        years = list(range(year_start, year_end + 1))
    elif year_start:
        years = [year_start]
    elif year_end:
        years = [year_end]

    queries: list[str] = []
    if years:
        for year in years:
            queries.extend(
                [
                    f"site:amazon.com/dp {keyword} {year} children book",
                    f"site:amazon.com {keyword} {year} ISBN",
                    f"amazon {keyword} {year} picture book",
                    f"{keyword} {year} ISBN amazon",
                    f"amazon {keyword} {year} illustrated",
                    f"{keyword} {year} book author amazon",
                    f"amazon {keyword} {year} paperback",
                    f"amazon {keyword} {year} hardcover",
                    f"{keyword} published {year} amazon",
                    f"site:isbnsearch.org {keyword} {year} children book",
                    f"site:worldcat.org {keyword} {year} juvenile ISBN",
                    f"{keyword} {year} picture book ISBN author",
                    f"{keyword} {year} ASIN picture book author",
                    f"site:goodreads.com {keyword} {year} ISBN children",
                    f"site:barnesandnoble.com/w {keyword} {year} ISBN",
                    f"site:bookshop.org {keyword} {year} ISBN children",
                    f"{keyword} {year} publisher ISBN children book",
                ]
            )
    else:
        queries.extend(
            [
                f"site:amazon.com/dp {keyword} children book",
                f"site:amazon.com {keyword} ISBN children",
                f"amazon {keyword} picture book",
                f"{keyword} amazon books ISBN",
                f"amazon {keyword} illustrated",
                f"{keyword} book author amazon",
                f"amazon {keyword} paperback",
                f"amazon {keyword} hardcover",
                f"site:isbnsearch.org {keyword} children book",
                f"site:worldcat.org {keyword} juvenile ISBN",
                f"{keyword} picture book ISBN author",
                f"{keyword} juvenile fiction ISBN",
                f"{keyword} ASIN picture book author",
                f"site:goodreads.com {keyword} ISBN children",
                f"site:barnesandnoble.com/w {keyword} ISBN",
                f"site:bookshop.org {keyword} ISBN children",
                f"{keyword} publisher ISBN children book",
            ]
        )
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
    }
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


def candidate_from_search_result(
    dto: SearchResultDTO,
    source_name: str,
    year_start: int | None,
    year_end: int | None,
) -> dict | None:
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
    return build_book_record(
        code=code,
        title=title or dto.title,
        author_name=author,
        publication_date=publication_date,
        source=source_name,
        source_url=dto.url,
        source_title=dto.title,
        source_snippet=dto.snippet or "",
        book_data_confidence=confidence,
        year_start=year_start,
        year_end=year_end,
    )


def candidate_from_catalog_result(
    raw: dict,
    source_name: str,
    year_start: int | None = None,
    year_end: int | None = None,
) -> dict | None:
    code = normalize_book_code(raw.get("asin") or raw.get("isbn"))
    source_raw = raw.get("source_raw_json") or {}
    source_url = raw.get("source_url") or raw.get("amazon_source_url") or source_raw.get("info_link") or ""
    source_title = raw.get("source_title") or raw.get("amazon_source_title") or raw.get("title") or ""
    source_snippet = raw.get("source_snippet") or raw.get("amazon_source_snippet") or source_raw.get("description") or ""
    return build_book_record(
        code=code,
        title=raw.get("title") or source_title,
        author_name=raw.get("author_name") or "",
        publication_date=str(raw.get("publication_date") or ""),
        cover_image_url=raw.get("cover_image_url") or "",
        publisher=raw.get("publisher") or "",
        category=raw.get("category") or "",
        source=source_name,
        source_url=source_url,
        source_title=source_title,
        source_snippet=source_snippet,
        book_data_confidence=float(raw.get("book_data_confidence") or 0.65),
        require_childrens_signal=False,
        year_start=year_start,
        year_end=year_end,
    )


def append_new_books(
    *,
    candidates: Iterable[dict | None],
    all_books: list[dict],
    seen_ids: set[str],
    max_results: int,
    books_yielded: int = 0,
    only_new: bool = False,
) -> list[dict]:
    batch: list[dict] = []
    for candidate in candidates:
        limit_check = books_yielded if only_new else len(all_books)
        if limit_check >= max_results:
            break
        if not candidate:
            continue
        code = str(candidate.get("asin") or candidate.get("isbn") or "").upper()
        dedupe_key = canonical_book_key(code)
        if not code or not dedupe_key or dedupe_key in seen_ids:
            continue
        seen_ids.add(dedupe_key)
        all_books.append(candidate)
        batch.append(candidate)
        books_yielded += 1
    return batch


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

    yield {
        "status": "starting",
        "message": "Checking saved keyword folder before DDGS search...",
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

    queries = build_queries(keyword, year_start, year_end)
    deep_query_limit = int(getattr(settings, "APP_ISBN_LOOKUP_DEEP_QUERY_LIMIT", max(24, min(len(queries), max_results))))
    queries = queries[: max(1, min(len(queries), deep_query_limit))]
    providers = [
        ("ddgs", DDGSSearchProvider(), 30),
        ("ddgs_html", DDGHTMLSearchProvider(delay=0.4), 30),
    ]
    total_steps = len(queries) * len(providers)
    step = 0
    # Web snippets are useful for Amazon URL discovery, but they must not crowd
    # authoritative catalogs out of the result budget on normal-sized runs.
    catalog_reserve = max(1, round(max_results * 0.4)) if max_results >= 5 else 0
    web_result_cap = max_results - catalog_reserve

    for provider_name, provider, result_limit in providers:
        layer_label = "Layer 2/7" if provider_name == "ddgs" else "Layer 3/7"
        for query in queries:
            if books_yielded >= web_result_cap:
                break
            step += 1
            queries_run.append(f"{provider_name}: {query}")
            yield {
                "status": "searching",
                "message": f"[{step}/{total_steps}] {layer_label}: {provider_name.upper()} scanning: {query}",
                "count": books_yielded,
                "cache_hit": bool(cached_books),
            }
            try:
                results = provider.search(query, max_results=result_limit)
            except Exception as exc:
                logger.warning("%s ISBN keyword query failed for %r: %s", provider_name, query, exc)
                continue

            batch = append_new_books(
                candidates=(
                    candidate_from_search_result(dto, provider_name, year_start, year_end)
                    for dto in results
                ),
                all_books=all_books,
                seen_ids=seen_ids,
                max_results=web_result_cap,
                books_yielded=books_yielded,
                only_new=only_new,
            )
            
            if only_new:
                books_yielded += len(batch)
            else:
                books_yielded = min(len(all_books), max_results)

            if batch:
                cache_path = save_cached_books(keyword, year_start, year_end, all_books, queries_run)
                yield {
                    "status": "progress",
                    "message": f"Saved {len(batch)} new books to keyword folder.",
                    "books": batch,
                    "count": books_yielded,
                    "cache_updated": True,
                    "cache_path": str(cache_path),
                }
            time.sleep(0.1)

    # Google Books Fallback Layer
    if books_yielded < max_results:
        yield {
            "status": "searching",
            "message": f"Layer 4/7: Google Books API lookup for: {keyword}",
            "count": books_yielded,
            "cache_hit": bool(cached_books),
        }
        try:
            gb = GoogleBooksProvider()
            gb_results = gb.discover_books(keyword, max_books=max_results - books_yielded)
            batch = append_new_books(
                candidates=(
                    candidate_from_catalog_result(raw, "google_books", year_start, year_end)
                    for raw in gb_results
                ),
                all_books=all_books,
                seen_ids=seen_ids,
                max_results=max_results,
                books_yielded=books_yielded,
                only_new=only_new,
            )
            if only_new:
                books_yielded += len(batch)
            else:
                books_yielded = min(len(all_books), max_results)

            if batch:
                cache_path = save_cached_books(keyword, year_start, year_end, all_books, queries_run)
                yield {
                    "status": "progress",
                    "message": f"Saved {len(batch)} new books from Google Books to keyword folder.",
                    "books": batch,
                    "count": books_yielded,
                    "cache_updated": True,
                    "cache_path": str(cache_path),
                }
        except Exception as exc:
            logger.warning("Google Books fallback lookup failed: %s", exc)

    # Open Library Fallback Layer
    if books_yielded < max_results:
        yield {
            "status": "searching",
            "message": f"Layer 5/7: Open Library API lookup for: {keyword}",
            "count": books_yielded,
            "cache_hit": bool(cached_books),
        }
        try:
            ol_results = search_openlibrary(
                keyword,
                year_start=year_start,
                year_end=year_end,
                max_books=max_results - books_yielded,
            )
            batch = append_new_books(
                candidates=(
                    candidate_from_catalog_result(raw, "open_library", year_start, year_end)
                    for raw in ol_results
                ),
                all_books=all_books,
                seen_ids=seen_ids,
                max_results=max_results,
                books_yielded=books_yielded,
                only_new=only_new,
            )
            if only_new:
                books_yielded += len(batch)
            else:
                books_yielded = min(len(all_books), max_results)

            if batch:
                cache_path = save_cached_books(keyword, year_start, year_end, all_books, queries_run)
                yield {
                    "status": "progress",
                    "message": f"Saved {len(batch)} new books from Open Library to keyword folder.",
                    "books": batch,
                    "count": books_yielded,
                    "cache_updated": True,
                    "cache_path": str(cache_path),
                }
        except Exception as exc:
            logger.warning("Open Library fallback lookup failed: %s", exc)

    # Library of Congress is the final no-key catalog fallback. It is deliberately
    # bounded and internally cached to respect the public service.
    if books_yielded < max_results:
        yield {
            "status": "searching",
            "message": f"Layer 6/7: Library of Congress lookup for: {keyword}",
            "count": books_yielded,
            "cache_hit": bool(cached_books),
        }
        try:
            loc_results = search_library_of_congress(
                keyword,
                year_start=year_start,
                year_end=year_end,
                max_books=max_results - books_yielded,
            )
            batch = append_new_books(
                candidates=(
                    candidate_from_catalog_result(raw, "library_of_congress", year_start, year_end)
                    for raw in loc_results
                ),
                all_books=all_books,
                seen_ids=seen_ids,
                max_results=max_results,
                books_yielded=books_yielded,
                only_new=only_new,
            )
            if only_new:
                books_yielded += len(batch)
            else:
                books_yielded = min(len(all_books), max_results)
            if batch:
                cache_path = save_cached_books(keyword, year_start, year_end, all_books, queries_run)
                yield {
                    "status": "progress",
                    "message": f"Saved {len(batch)} new books from the Library of Congress.",
                    "books": batch,
                    "count": books_yielded,
                    "cache_updated": True,
                    "cache_path": str(cache_path),
                }
        except Exception as exc:
            logger.warning("Library of Congress fallback lookup failed: %s", exc)

    if all_books:
        ai_completed = sum(1 for book in all_books if book.get("ai_metadata_completed"))
        ai_attempted = any(book.get("ai_metadata_attempted") for book in all_books)
        yield {
            "status": "searching",
            "message": (
                f"Layer 7/7: Groq metadata refinement completed for {ai_completed} books."
                if ai_attempted
                else "Layer 7/7: Optional Groq refinement unavailable; deterministic validation retained."
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
