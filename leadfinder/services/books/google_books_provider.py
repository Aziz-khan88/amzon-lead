from __future__ import annotations

import logging
import os
from urllib.parse import urlencode

import requests
from requests import HTTPError
from django.conf import settings

from leadfinder.utils.normalize import is_valid_author_name, normalized_book_key

logger = logging.getLogger(__name__)


GOOGLE_BOOKS_ENDPOINT = "https://www.googleapis.com/books/v1/volumes"


class GoogleBooksProvider:
    provider_name = "google_books"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("GOOGLE_BOOKS_API_KEY", "")
        self.last_errors: list[str] = []

    def is_configured(self) -> bool:
        return True

    def discover_books(self, keyword: str, max_books: int = 25) -> list[dict]:
        self.last_errors = []
        candidates: list[dict] = []
        seen_keys: set[str] = set()
        for query in self._queries(keyword):
            if len(candidates) >= max_books:
                break
            try:
                for item in self._search(query, max_results=min(40, max_books * 2)):
                    candidate = self._candidate_from_volume(item, query)
                    if not candidate:
                        continue
                    key = normalized_book_key(candidate["title"], candidate["author_name"], candidate.get("asin"))
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    candidates.append(candidate)
                    if len(candidates) >= max_books:
                        break
            except Exception as exc:
                self.last_errors.append(f"{query}: {exc}")
                logger.warning("Google Books query failed for %r: %s", query, exc)
        candidates.sort(key=lambda item: item.get("book_data_confidence", 0), reverse=True)
        return candidates[:max_books]

    def _queries(self, keyword: str) -> list[str]:
        cleaned = " ".join((keyword or "").split())
        if not cleaned:
            return []
        queries = [
            cleaned,
            f'{cleaned} children picture book',
            f'{cleaned} juvenile fiction',
            f'intitle:{cleaned}',
            f'subject:juvenile {cleaned}',
        ]
        return list(dict.fromkeys(queries))

    def _search(self, query: str, max_results: int) -> list[dict]:
        params = {
            "q": query,
            "maxResults": max(1, min(max_results, 40)),
            "printType": "books",
            "projection": "full",
            "orderBy": "relevance",
        }
        if self.api_key:
            params["key"] = self.api_key
        try:
            response = self._request(params)
        except HTTPError as exc:
            status_code = getattr(exc.response, "status_code", None)
            if status_code != 403 or not params.pop("key", None):
                raise
            response = self._request(params)
        return response.json().get("items", []) or []

    def _request(self, params: dict) -> requests.Response:
        url = f"{GOOGLE_BOOKS_ENDPOINT}?{urlencode(params)}"
        response = requests.get(url, timeout=getattr(settings, "APP_REQUEST_TIMEOUT_SECONDS", 15))
        response.raise_for_status()
        return response

    def _candidate_from_volume(self, item: dict, query: str) -> dict | None:
        volume = item.get("volumeInfo") or {}
        title = (volume.get("title") or "").strip()
        subtitle = (volume.get("subtitle") or "").strip()
        if subtitle and subtitle.lower() not in title.lower():
            title = f"{title}: {subtitle}"
        authors = [name.strip() for name in volume.get("authors", []) if is_valid_author_name(name.strip())]
        if not title or not authors:
            return None

        categories = volume.get("categories", []) or []
        if not self._looks_like_childrens_book(title, volume.get("description", ""), categories):
            return None

        identifiers = volume.get("industryIdentifiers", []) or []
        isbn13 = self._identifier(identifiers, "ISBN_13")
        isbn10 = self._identifier(identifiers, "ISBN_10")
        isbn = isbn13 or isbn10
        source_url = volume.get("canonicalVolumeLink") or volume.get("infoLink") or item.get("selfLink") or ""
        image_links = volume.get("imageLinks") or {}
        cover = (
            image_links.get("extraLarge")
            or image_links.get("large")
            or image_links.get("medium")
            or image_links.get("thumbnail")
            or image_links.get("smallThumbnail")
            or ""
        )
        if cover.startswith("http://"):
            cover = "https://" + cover.removeprefix("http://")

        confidence = self._confidence(volume, bool(isbn), bool(cover))
        return {
            "title": title[:500],
            "author_name": authors[0][:255],
            "asin": isbn[:20] if isbn else "",
            "amazon_book_url": "",
            "amazon_source_url": source_url,
            "amazon_source_title": title,
            "amazon_source_snippet": (volume.get("description") or "")[:1000],
            "category": "; ".join(categories)[:255],
            "review_count": volume.get("ratingsCount"),
            "rating": volume.get("averageRating"),
            "publisher": (volume.get("publisher") or "")[:255],
            "publication_date": (volume.get("publishedDate") or "")[:100],
            "cover_image_url": cover,
            "book_data_confidence": confidence,
            "source_provider": self.provider_name,
            "source_raw_json": {
                "query": query,
                "google_volume_id": item.get("id", ""),
                "google_self_link": item.get("selfLink", ""),
                "info_link": volume.get("infoLink", ""),
                "canonical_volume_link": volume.get("canonicalVolumeLink", ""),
                "authors": authors,
                "industry_identifiers": identifiers,
                "categories": categories,
                "language": volume.get("language", ""),
                "maturity_rating": volume.get("maturityRating", ""),
                "description": (volume.get("description") or "")[:2000],
            },
        }

    def _identifier(self, identifiers: list[dict], id_type: str) -> str:
        for item in identifiers:
            if item.get("type") == id_type:
                return "".join(ch for ch in item.get("identifier", "") if ch.isalnum()).upper()
        return ""

    def _looks_like_childrens_book(self, title: str, description: str, categories: list[str]) -> bool:
        text = " ".join([title, description, " ".join(categories)]).lower()
        strong_terms = [
            "juvenile",
            "children",
            "childrens",
            "kids",
            "picture book",
            "bedtime",
            "preschool",
            "early reader",
            "storybook",
        ]
        reject_terms = ["adult", "erotica", "mature"]
        return any(term in text for term in strong_terms) and not any(term in text for term in reject_terms)

    def _confidence(self, volume: dict, has_isbn: bool, has_cover: bool) -> float:
        confidence = 0.55
        if has_isbn:
            confidence += 0.15
        if volume.get("publisher"):
            confidence += 0.07
        if volume.get("publishedDate"):
            confidence += 0.05
        if volume.get("description"):
            confidence += 0.06
        if volume.get("categories"):
            confidence += 0.05
        if has_cover:
            confidence += 0.04
        if volume.get("averageRating") or volume.get("ratingsCount"):
            confidence += 0.03
        return min(confidence, 0.95)
