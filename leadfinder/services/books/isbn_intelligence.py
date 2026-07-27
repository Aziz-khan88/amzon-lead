"""ISBN/ASIN validation, free metadata reconciliation, and barcode helpers.

The module deliberately separates *syntactic validity* from *issued-book metadata*.
A checksum can prove that an ISBN is structurally valid, but only matching public
catalog records can provide evidence that it was assigned to a particular book.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass
from io import BytesIO
from typing import Any

import barcode
import isbnlib
import pyisbn
import requests
from barcode.writer import SVGWriter
from django.conf import settings
from django.core.cache import cache
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from leadfinder.services.amazon.amazon_url_parser import extract_asin, is_amazon_url

ASIN_RE = re.compile(r"^B0[A-Z0-9]{8}$")
TOKEN_RE = re.compile(
    r"https?://[^\s,;]+|(?:97[89][\s-]?)?(?:\d[\s-]?){9}[\dXx]|\b[A-Za-z0-9]{10}\b",
    re.I,
)
USER_AGENT = "BookTrailerLeadFinder/1.0 (public book metadata reconciliation)"


@dataclass(frozen=True)
class IdentifierAnalysis:
    raw: str
    canonical: str
    identifier_type: str
    valid: bool
    confidence: float
    display: str
    isbn10: str
    isbn13: str
    checks: dict[str, bool]
    warnings: list[str]
    barcode_available: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _internal_isbn10_valid(code: str) -> bool:
    if not re.fullmatch(r"\d{9}[\dX]", code):
        return False
    return (
        sum(
            (index + 1) * (10 if char == "X" else int(char))
            for index, char in enumerate(code)
        )
        % 11
        == 0
    )


def _internal_isbn13_valid(code: str) -> bool:
    if not re.fullmatch(r"\d{13}", code) or not code.startswith(("978", "979")):
        return False
    check = (
        10
        - sum(
            (1 if index % 2 == 0 else 3) * int(char)
            for index, char in enumerate(code[:12])
        )
        % 10
    ) % 10
    return check == int(code[-1])


def analyze_identifier(value: str | None) -> IdentifierAnalysis:
    raw = (value or "").strip()
    candidate = extract_asin(raw) if is_amazon_url(raw) else raw
    canonical = isbnlib.canonical(candidate).upper()
    warnings: list[str] = []

    if len(canonical) in {10, 13}:
        is_10 = len(canonical) == 10
        checks = {
            "internal_checksum": (
                _internal_isbn10_valid(canonical)
                if is_10
                else _internal_isbn13_valid(canonical)
            ),
            "isbnlib": bool(
                isbnlib.is_isbn10(canonical) if is_10 else isbnlib.is_isbn13(canonical)
            ),
            "pyisbn": bool(pyisbn.validate(canonical)),
        }
        agreement = sum(checks.values())
        valid = agreement == len(checks)
        if agreement and not valid:
            warnings.append("ISBN validators disagreed; manual review is required.")
        if not agreement:
            warnings.append("The ISBN checksum is invalid.")

        isbn10 = canonical if is_10 and valid else ""
        isbn13 = canonical if not is_10 and valid else ""
        if valid:
            try:
                converted = pyisbn.convert(canonical)
            except (TypeError, ValueError):
                converted = ""
            if is_10:
                isbn13 = isbnlib.to_isbn13(canonical) or converted
            elif canonical.startswith("978"):
                isbn10 = isbnlib.to_isbn10(canonical) or converted
            display = isbnlib.mask(canonical) or canonical
        else:
            display = canonical or raw

        return IdentifierAnalysis(
            raw=raw,
            canonical=canonical,
            identifier_type="isbn10" if is_10 else "isbn13",
            valid=valid,
            confidence=1.0 if valid else round(agreement / len(checks), 2),
            display=display,
            isbn10=isbn10,
            isbn13=isbn13,
            checks=checks,
            warnings=warnings,
            barcode_available=bool(isbn13),
        )

    asin = re.sub(r"[^A-Za-z0-9]", "", candidate).upper()
    asin_valid = bool(ASIN_RE.fullmatch(asin) and any(char.isalpha() for char in asin))
    if not asin_valid:
        warnings.append("Expected a valid ISBN-10, ISBN-13, ASIN, or Amazon book URL.")
    elif not asin.startswith("B"):
        warnings.append(
            "ASIN syntax is valid, but catalog assignment still requires source evidence."
        )
    return IdentifierAnalysis(
        raw=raw,
        canonical=asin,
        identifier_type="asin" if asin_valid else "unknown",
        valid=asin_valid,
        confidence=0.65 if asin_valid else 0.0,
        display=asin or raw,
        isbn10="",
        isbn13="",
        checks={"asin_syntax": asin_valid},
        warnings=warnings,
        barcode_available=False,
    )


def parse_identifier_batch(
    value: str | None,
) -> tuple[list[IdentifierAnalysis], list[str]]:
    """Extract, canonicalize, validate, and deduplicate a mixed identifier batch."""
    text = value or ""
    matches = TOKEN_RE.findall(text)
    if not matches and text.strip():
        matches = [part for part in re.split(r"[\s,;]+", text) if part]

    valid: list[IdentifierAnalysis] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for token in matches:
        analysis = analyze_identifier(token.rstrip(".)]}>"))
        if not analysis.valid:
            invalid.append(token)
            continue
        dedupe_key = analysis.isbn13 or analysis.canonical
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        valid.append(analysis)
    return valid, invalid


def generate_barcode_svg(value: str) -> bytes:
    analysis = analyze_identifier(value)
    if not analysis.valid or not analysis.isbn13:
        raise ValueError(
            "A valid ISBN-10 or ISBN-13 is required for barcode generation."
        )
    output = BytesIO()
    barcode.get("isbn13", analysis.isbn13, writer=SVGWriter()).write(
        output,
        options={
            "module_height": 12,
            "quiet_zone": 3,
            "font_size": 8,
            "text_distance": 3,
            "background": "ffffff",
            "foreground": "111827",
        },
    )
    return output.getvalue()


def _request_json(
    session: requests.Session, url: str, *, params: dict[str, Any]
) -> dict[str, Any]:
    response = session.get(
        url,
        params=params,
        timeout=getattr(settings, "APP_REQUEST_TIMEOUT_SECONDS", 15),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _open_library_record(session: requests.Session, isbn: str) -> dict[str, Any] | None:
    url = "https://openlibrary.org/api/books"
    key = f"ISBN:{isbn}"
    payload = _request_json(
        session, url, params={"bibkeys": key, "format": "json", "jscmd": "data"}
    )
    item = payload.get(key)
    if not isinstance(item, dict):
        return None
    authors = [
        entry.get("name", "").strip()
        for entry in item.get("authors", [])
        if entry.get("name")
    ]
    publishers = [
        entry.get("name", "").strip()
        for entry in item.get("publishers", [])
        if entry.get("name")
    ]
    cover = item.get("cover") or {}
    return {
        "provider": "open_library",
        "source_url": item.get("url") or f"https://openlibrary.org/isbn/{isbn}",
        "title": (item.get("title") or "").strip(),
        "authors": authors,
        "publisher": publishers[0] if publishers else "",
        "publication_date": (item.get("publish_date") or "").strip(),
        "cover_image_url": cover.get("large")
        or cover.get("medium")
        or cover.get("small")
        or "",
        "description": "",
    }


def _google_books_record(session: requests.Session, isbn: str) -> dict[str, Any] | None:
    url = "https://www.googleapis.com/books/v1/volumes"
    payload = _request_json(
        session,
        url,
        params={
            "q": f"isbn:{isbn}",
            "maxResults": 5,
            "printType": "books",
            "projection": "full",
        },
    )
    requested = analyze_identifier(isbn)
    equivalent_ids = {
        value
        for value in {requested.canonical, requested.isbn10, requested.isbn13}
        if value
    }
    for item in payload.get("items", []) or []:
        volume = item.get("volumeInfo") or {}
        identifiers = {
            re.sub(r"\W", "", entry.get("identifier", "")).upper()
            for entry in volume.get("industryIdentifiers", []) or []
        }
        if not equivalent_ids.intersection(identifiers):
            continue
        images = volume.get("imageLinks") or {}
        cover = next(
            (
                images.get(size)
                for size in (
                    "extraLarge",
                    "large",
                    "medium",
                    "thumbnail",
                    "smallThumbnail",
                )
                if images.get(size)
            ),
            "",
        )
        return {
            "provider": "google_books",
            "source_url": volume.get("canonicalVolumeLink")
            or volume.get("infoLink")
            or item.get("selfLink")
            or url,
            "title": (volume.get("title") or "").strip(),
            "authors": [
                name.strip() for name in volume.get("authors", []) if name.strip()
            ],
            "publisher": (volume.get("publisher") or "").strip(),
            "publication_date": (volume.get("publishedDate") or "").strip(),
            "cover_image_url": (cover or "").replace("http://", "https://", 1),
            "description": (volume.get("description") or "").strip(),
        }
    return None


def _normalize_agreement(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _choose_field(
    records: list[dict[str, Any]], field: str
) -> tuple[Any, dict[str, Any]]:
    values = [
        (record["provider"], record.get(field))
        for record in records
        if record.get(field)
    ]
    if not values:
        return ([] if field == "authors" else ""), {"agreement": 0.0, "sources": []}
    normalized = [_normalize_agreement(value) for _, value in values]
    most_common, count = Counter(normalized).most_common(1)[0]
    selected = next(
        value for (_, value), norm in zip(values, normalized) if norm == most_common
    )
    return selected, {
        "agreement": round(count / len(values), 2),
        "sources": [
            {"provider": provider, "value": value} for provider, value in values
        ],
    }


def resolve_free_metadata(
    value: str, *, session: requests.Session | None = None
) -> dict[str, Any]:
    """Reconcile exact-ISBN results from public, no-key catalog APIs.

    Providers are free/no-key, not unlimited. Their published fair-use and rate
    limits still apply, so successful results are cached for 24 hours.
    """
    analysis = analyze_identifier(value)
    if not analysis.valid or analysis.identifier_type not in {"isbn10", "isbn13"}:
        return {
            "identifier": analysis.as_dict(),
            "metadata": {},
            "sources": [],
            "confidence": 0.0,
            "warnings": analysis.warnings,
        }

    lookup_isbn = analysis.isbn13 or analysis.canonical
    cache_key = f"isbn-intelligence:v1:{lookup_isbn}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return {**cached, "cache_hit": True}

    http = session or requests.Session()
    if session is None:
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.35,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
        )
        http.mount("https://", HTTPAdapter(max_retries=retry))
    records: list[dict[str, Any]] = []
    provider_errors: list[str] = []
    for provider, fetcher in (
        ("open_library", _open_library_record),
        ("google_books", _google_books_record),
    ):
        try:
            record = fetcher(http, lookup_isbn)
            if record:
                records.append(record)
        except (requests.RequestException, ValueError) as exc:
            provider_errors.append(f"{provider}: {exc}")

    metadata: dict[str, Any] = {}
    field_evidence: dict[str, Any] = {}
    for field in (
        "title",
        "authors",
        "publisher",
        "publication_date",
        "cover_image_url",
        "description",
    ):
        metadata[field], field_evidence[field] = _choose_field(records, field)

    core_agreements = [
        field_evidence[field]["agreement"]
        for field in ("title", "authors")
        if field_evidence[field]["sources"]
    ]
    if not records:
        confidence = 0.0
    elif len(records) == 1:
        confidence = 0.52
    else:
        confidence = 0.62 + (
            (sum(core_agreements) / len(core_agreements)) * 0.25
            if core_agreements
            else 0
        )
    if records and metadata.get("publisher"):
        confidence += 0.04
    if records and metadata.get("publication_date"):
        confidence += 0.03
    confidence = round(min(confidence, 0.95), 2)

    warnings = list(analysis.warnings)
    if not records:
        warnings.append(
            "Checksum is valid, but no matching public catalog record was returned."
        )
    elif len(records) == 1:
        warnings.append(
            "Only one public catalog source matched; review before outreach."
        )
    elif any(score < 1.0 for score in core_agreements):
        warnings.append(
            "Public catalogs disagree on title or author; review the source evidence."
        )

    result = {
        "identifier": analysis.as_dict(),
        "metadata": metadata,
        "sources": records,
        "field_evidence": field_evidence,
        "confidence": confidence,
        "warnings": warnings,
        "provider_errors": provider_errors,
        "cache_hit": False,
    }
    cache.set(cache_key, result, timeout=60 * 60 * 24 if records else 60 * 10)
    return result


def public_resolution_to_book_data(resolution: dict[str, Any]) -> dict[str, Any] | None:
    metadata = resolution.get("metadata") or {}
    if not metadata.get("title"):
        return None
    return {
        "title": metadata.get("title", ""),
        "authors": [{"name": name, "url": ""} for name in metadata.get("authors", [])],
        "publisher": metadata.get("publisher", ""),
        "publication_date": metadata.get("publication_date", ""),
        "cover_image_url": metadata.get("cover_image_url", ""),
        "description": metadata.get("description", ""),
        "scraped_successfully": bool(resolution.get("sources")),
        "metadata_sources": resolution.get("sources", []),
        "metadata_field_evidence": resolution.get("field_evidence", {}),
        "metadata_confidence": resolution.get("confidence", 0.0),
        "metadata_warnings": resolution.get("warnings", []),
    }
