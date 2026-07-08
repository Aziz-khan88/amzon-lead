from __future__ import annotations

import html
import os
import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from django.conf import settings

from leadfinder.services.crawl.extract_links import extract_links, extract_social_links
from leadfinder.services.crawl.robots import can_fetch_url
from leadfinder.services.crawl.safe_fetch import USER_AGENT, safe_fetch
from leadfinder.utils.normalize import clean_author_name, normalized_book_key


BOOKLIFE_BASE_URL = "https://booklife.com"
PROJECT_PATH_RE = re.compile(r"^/project/[^/?#]+-\d+/?$")
TRUE_VALUES = {"1", "true", "yes", "on"}


class BookLifeRobotsBlocked(RuntimeError):
    """Raised when BookLife disallows direct crawling for our user agent."""


@dataclass(frozen=True)
class BookLifeCategory:
    slug: str
    label: str
    group: str


BOOKLIFE_AGE_FILTERS = [
    ("all", "All"),
    ("adult", "Adult"),
    ("children-young-adult", "Children / Young Adult"),
]


BOOKLIFE_CATEGORIES = [
    BookLifeCategory("", "All categories", "Featured"),
    BookLifeCategory("fiction-mystery-thriller", "Mystery/Thriller", "Fiction"),
    BookLifeCategory("fiction-sci-fi-fantasy-horror", "Sci-Fi/Fantasy/Horror", "Fiction"),
    BookLifeCategory("fiction-romance", "Romance", "Fiction"),
    BookLifeCategory(
        "fiction-general-fiction-including-literary-and-historical-",
        "General Fiction (including literary and historical)",
        "Fiction",
    ),
    BookLifeCategory("nonfiction-true-crime", "True Crime", "Nonfiction"),
    BookLifeCategory("nonfiction-history-military", "History & Military", "Nonfiction"),
    BookLifeCategory("nonfiction-memoir", "Memoir", "Nonfiction"),
    BookLifeCategory("nonfiction-food-cooking", "Food & Cooking", "Nonfiction"),
    BookLifeCategory(
        "nonfiction-health-diet-parenting-home-crafts-gardening",
        "Health, Diet, Parenting, Home, Crafts & Gardening",
        "Nonfiction",
    ),
    BookLifeCategory(
        "nonfiction-self-help-sex-relationships-psychology-philosophy-fashion",
        "Self-Help, Sex & Relationships, Psychology, Philosophy, Fashion",
        "Nonfiction",
    ),
    BookLifeCategory("nonfiction-business-personal-finance", "Business & Personal Finance", "Nonfiction"),
    BookLifeCategory("nonfiction-pop-culture-sports", "Pop Culture & Sports", "Nonfiction"),
    BookLifeCategory("nonfiction-music-performing-arts-travel", "Music, Performing Arts, Travel", "Nonfiction"),
    BookLifeCategory("nonfiction-political-social-sciences", "Political & Social Sciences", "Nonfiction"),
    BookLifeCategory("nonfiction-art-photography", "Art & Photography", "Nonfiction"),
    BookLifeCategory("nonfiction-science-nature-technology", "Science, Nature, Technology", "Nonfiction"),
    BookLifeCategory("nonfiction-lit-crit-lit-bio-essay-film", "Lit Crit, Lit Bio, Essay, Film", "Nonfiction"),
    BookLifeCategory("nonfiction-other-nonfiction", "Other Nonfiction", "Nonfiction"),
    BookLifeCategory("poetry", "Poetry", "Other"),
    BookLifeCategory("comics-graphic-novels", "Comics/Graphic Novels", "Other"),
    BookLifeCategory("spirituality-inspirational", "Spirituality/Inspirational", "Other"),
]


def booklife_category_choices() -> list[tuple[str, str]]:
    return [(category.slug or "all", category.label) for category in BOOKLIFE_CATEGORIES]


def grouped_booklife_categories() -> list[dict]:
    groups: dict[str, list[BookLifeCategory]] = {}
    for category in BOOKLIFE_CATEGORIES:
        groups.setdefault(category.group, []).append(category)
    return [{"label": label, "categories": categories} for label, categories in groups.items()]


def _compact_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def _humanize_project_slug(url: str) -> str:
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"-\d+$", "", slug)
    words = [word for word in slug.split("-") if word]
    return " ".join(words).title()


def _category_by_slug(slug: str) -> BookLifeCategory:
    normalized_slug = "" if slug == "all" else slug
    for category in BOOKLIFE_CATEGORIES:
        if category.slug == normalized_slug:
            return category
    raise ValueError(f"Unknown BookLife category: {slug}")


def _category_url(category_slug: str, age_filter: str) -> str:
    category = _category_by_slug(category_slug)
    age = age_filter if age_filter in {value for value, _label in BOOKLIFE_AGE_FILTERS} else "all"
    if category.slug:
        return f"{BOOKLIFE_BASE_URL}/project-browse/{age}/{category.slug}"
    return f"{BOOKLIFE_BASE_URL}/project-browse/{age}"


def _external_non_social_links(links: list[str]) -> list[str]:
    excluded_hosts = {"www.mediapolis.com", "mediapolis.com", "sonyabalchandani.com", "www.sonyabalchandani.com"}
    external_links: list[str] = []
    for link in links:
        parsed = urlparse(link)
        host = (parsed.hostname or "").lower()
        if not host or host.endswith("booklife.com") or host in excluded_hosts:
            continue
        if any(domain in host for domain in ["facebook.com", "instagram.com", "tiktok.com", "youtube.com", "youtu.be", "linkedin.com", "goodreads.com"]):
            continue
        if any(domain in host for domain in ["amazon.", "barnesandnoble.", "bookshop.", "kobo.", "audible."]):
            continue
        if link not in external_links:
            external_links.append(link)
    return external_links


class BookLifeProjectProvider:
    provider_name = "booklife"

    def __init__(self, *, fetch_project_details: bool = False):
        self.fetch_project_details = fetch_project_details
        self.allow_direct_fetch = os.getenv("BOOKLIFE_DIRECT_FETCH_ALLOWED", "").lower() in TRUE_VALUES

    def discover_books(
        self,
        *,
        category_slugs: list[str],
        age_filter: str = "all",
        max_books: int = 25,
    ) -> list[dict]:
        candidates: list[dict] = []
        seen_keys: set[str] = set()
        selected_categories = category_slugs or ["all"]

        for category_slug in selected_categories:
            if len(candidates) >= max_books:
                break
            category = _category_by_slug(category_slug)
            next_url = _category_url(category_slug, age_filter)
            visited_pages: set[str] = set()

            while next_url and next_url not in visited_pages and len(candidates) < max_books:
                visited_pages.add(next_url)
                page = self._fetch_page(next_url)
                page_candidates = self.parse_project_cards(page.html, next_url, category)
                for candidate in page_candidates:
                    key = normalized_book_key(candidate["title"], candidate.get("author_name"), "")
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    if self.fetch_project_details:
                        self._merge_project_detail(candidate)
                    candidates.append(candidate)
                    if len(candidates) >= max_books:
                        break
                next_url = self._next_page_url(page.html, next_url)

        return candidates[:max_books]

    def search_index_queries(self, *, category_slugs: list[str], age_filter: str = "all") -> list[str]:
        queries: list[str] = []
        selected_categories = category_slugs or ["all"]
        for category_slug in selected_categories:
            category = _category_by_slug(category_slug)
            category_terms = "" if category.slug == "" else f' "{category.label}"'
            age_terms = ' "children"' if age_filter == "children-young-adult" else ""
            queries.extend(
                [
                    f'site:booklife.com/project/ "by" "BookLife"{category_terms}{age_terms}',
                    f'site:booklife.com/project/ "{category.label}" "by"',
                ]
            )
        return list(dict.fromkeys(queries))

    def candidate_from_search_result(self, dto, category_slug: str) -> dict | None:
        parsed = urlparse(dto.url)
        if not parsed.netloc.endswith("booklife.com") or not PROJECT_PATH_RE.match(parsed.path):
            return None
        category = _category_by_slug(category_slug)
        title = self._title_from_search_result(dto.title, dto.url)
        author = self._author_from_search_result(dto.title, dto.snippet or "")
        if not title:
            return None
        project_url = f"{parsed.scheme or 'https'}://{parsed.netloc}{parsed.path}"
        snippet = _compact_text(dto.snippet or "")
        return {
            "title": title[:500],
            "author_name": author[:255],
            "category": category.label,
            "booklife_project_url": project_url,
            "amazon_source_url": project_url,
            "amazon_source_title": dto.title[:500],
            "amazon_source_snippet": snippet[:1000],
            "book_data_confidence": 0.68 if author else 0.5,
            "source_provider": self.provider_name,
            "source_raw_json": {
                "source": "booklife_search_index",
                "project_url": project_url,
                "category": category.label,
                "category_slug": category.slug or "all",
                "search_rank": dto.rank,
                "direct_fetch_blocked": True,
            },
        }

    def _fetch_page(self, url: str):
        if not self.allow_direct_fetch and not can_fetch_url(url, USER_AGENT):
            raise BookLifeRobotsBlocked(
                "BookLife robots.txt currently disallows direct automated fetching for this user agent. "
                "The runner stopped before scraping BookLife pages. If you have written permission, set "
                "BOOKLIFE_DIRECT_FETCH_ALLOWED=1 and keep the request limits conservative."
            )
        if self.allow_direct_fetch:
            timeout = int(getattr(settings, "APP_REQUEST_TIMEOUT_SECONDS", 15))
            time.sleep(float(getattr(settings, "APP_REQUEST_DELAY_SECONDS", 1.5)))
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
                timeout=timeout,
                allow_redirects=True,
            )
            response.raise_for_status()
            return type(
                "FetchedBookLifePage",
                (),
                {
                    "url": response.url,
                    "status_code": response.status_code,
                    "html": response.text,
                    "content_type": response.headers.get("content-type", ""),
                },
            )()
        fetched = safe_fetch(url)
        if not fetched or fetched.status_code >= 400:
            raise RuntimeError(f"Could not fetch BookLife page: {url}")
        return fetched

    def _merge_project_detail(self, candidate: dict) -> None:
        project_url = candidate.get("booklife_project_url", "")
        if not project_url:
            return
        try:
            page = self._fetch_page(project_url)
        except Exception as exc:
            raw = dict(candidate.get("source_raw_json") or {})
            raw.setdefault("warnings", []).append(f"BookLife detail fetch skipped: {exc}")
            candidate["source_raw_json"] = raw
            return

        detail = self.parse_project_detail(page.html, page.url)
        raw = dict(candidate.get("source_raw_json") or {})
        raw.update(detail)
        candidate["source_raw_json"] = raw
        if detail.get("title"):
            candidate["title"] = detail["title"][:500]
            candidate["amazon_source_title"] = detail["title"][:500]
        if detail.get("author_name"):
            candidate["author_name"] = detail["author_name"][:255]
        if detail.get("detail_text") and len(detail["detail_text"]) > len(candidate.get("amazon_source_snippet", "")):
            candidate["amazon_source_snippet"] = detail["detail_text"][:1000]
        if detail.get("cover_image_url") and not candidate.get("cover_image_url"):
            candidate["cover_image_url"] = detail["cover_image_url"]

    def parse_project_cards(self, html_text: str, page_url: str, category: BookLifeCategory) -> list[dict]:
        soup = BeautifulSoup(html_text or "", "lxml")
        cards: list[dict] = []
        seen_urls: set[str] = set()

        for link in soup.find_all("a", href=True):
            href = urljoin(page_url, link["href"])
            parsed = urlparse(href)
            if not PROJECT_PATH_RE.match(parsed.path):
                continue
            title = _compact_text(link.get_text(" ", strip=True))
            if not title or title.lower() == "more":
                continue
            project_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if project_url in seen_urls:
                continue
            seen_urls.add(project_url)
            container = link.find_parent("li") or link.find_parent("article") or link.find_parent("div") or link.parent
            card_text = container.get_text("\n", strip=True) if container else title
            author = self._author_from_card_text(card_text)
            snippet = self._snippet_from_card_text(card_text, title, author)
            cover_image_url = self._cover_from_container(container, page_url)
            cards.append(
                {
                    "title": title[:500],
                    "author_name": author[:255],
                    "category": category.label,
                    "booklife_project_url": project_url,
                    "amazon_source_url": project_url,
                    "amazon_source_title": title,
                    "amazon_source_snippet": snippet[:1000],
                    "cover_image_url": cover_image_url,
                    "book_data_confidence": 0.78 if author else 0.62,
                    "source_provider": self.provider_name,
                    "source_raw_json": {
                        "source": "booklife",
                        "project_url": project_url,
                        "category": category.label,
                        "category_slug": category.slug or "all",
                        "browse_url": page_url,
                    },
                }
            )
        return cards

    def parse_project_detail(self, html_text: str, page_url: str) -> dict:
        soup = BeautifulSoup(html_text or "", "lxml")
        title = _compact_text((soup.select_one(".public-project-title") or soup.find("meta", property="og:title") or {}).get("content", ""))
        if not title and soup.select_one(".public-project-title"):
            title = _compact_text(soup.select_one(".public-project-title").get_text(" ", strip=True))
        title = re.sub(r"\s+by\s+.+?\s*\|\s*BookLife$", "", title, flags=re.I).strip()

        author_name = ""
        credit = soup.select_one(".public-project-credit")
        if credit:
            credit_text = _compact_text(credit.get_text(" ", strip=True))
            author_name = clean_author_name(re.sub(r",\s*author.*$", "", credit_text, flags=re.I))
        if not author_name:
            author_link = soup.select_one(".user-profile-card a.name, .public-project-credit a")
            if author_link:
                author_name = clean_author_name(_compact_text(author_link.get_text(" ", strip=True)))

        scoped_links = []
        for container in soup.select(".user-profile-social, .public-project-credit, .profile-social"):
            scoped_links.extend(extract_links(str(container), page_url))
        links = scoped_links or extract_links(html_text, page_url)
        socials = extract_social_links(links)

        synopsis_parts = [
            _compact_text(node.get_text(" ", strip=True))
            for node in soup.select(
                ".public-project-synopsis, .public-project-review p, .project-review p, "
                ".public-project-description, .book-description, .review-section p"
            )
        ]
        text = _compact_text(" ".join(part for part in synopsis_parts if part))
        if not text:
            description = soup.find("meta", attrs={"name": "description"})
            text = _compact_text(description.get("content", "") if description else "")
        cover = ""
        image = soup.find("meta", property="og:image") or soup.find("img")
        if image:
            cover = image.get("content") or image.get("src") or ""
            cover = urljoin(page_url, cover) if cover else ""
        profile_urls = [
            urljoin(page_url, link.get("href"))
            for link in soup.select('.user-profile-card a.name[href], .public-project-credit a[href]')
            if link.get("href", "").startswith("/profile/")
        ]
        return {
            "booklife_detail_url": page_url,
            "title": title,
            "author_name": author_name,
            "booklife_social_links": socials,
            "booklife_author_urls": _external_non_social_links(links),
            "booklife_profile_urls": list(dict.fromkeys(profile_urls)),
            "detail_text": text[:3000],
            "cover_image_url": cover,
        }

    def _next_page_url(self, html_text: str, page_url: str) -> str:
        soup = BeautifulSoup(html_text or "", "lxml")
        for link in soup.find_all("a", href=True):
            text = _compact_text(link.get_text(" ", strip=True))
            if text in {"\xbb", "Next", "next"}:
                return urljoin(page_url, link["href"])
        return ""

    def _author_from_card_text(self, card_text: str) -> str:
        lines = [_compact_text(line) for line in card_text.splitlines() if _compact_text(line)]
        for line in lines:
            match = re.match(r"^by\s+(.+)$", line, flags=re.I)
            if match:
                return _compact_text(match.group(1)).strip(" .")
        match = re.search(r"\bby\s+([^\n]+)", card_text, flags=re.I)
        return _compact_text(match.group(1)).strip(" .") if match else ""

    def _snippet_from_card_text(self, card_text: str, title: str, author: str) -> str:
        lines = [_compact_text(line) for line in card_text.splitlines() if _compact_text(line)]
        skipped = {title.lower(), "more"}
        if author:
            skipped.add(f"by {author}".lower())
        snippet_lines = [line for line in lines if line.lower() not in skipped]
        return " ".join(snippet_lines[:4])

    def _cover_from_container(self, container, page_url: str) -> str:
        if not container:
            return ""
        image = container.find("img")
        if not image:
            return ""
        src = image.get("src") or image.get("data-src") or ""
        return urljoin(page_url, src) if src else ""

    def _title_from_search_result(self, result_title: str, url: str) -> str:
        cleaned = _compact_text(result_title)
        cleaned = re.sub(r"\s*[-|:]\s*BookLife.*$", "", cleaned, flags=re.I).strip()
        if not cleaned or cleaned.lower() in {"booklife", "booklife - resources and tools for book publishers and writers"}:
            cleaned = _humanize_project_slug(url)
        return cleaned

    def _author_from_search_result(self, result_title: str, snippet: str) -> str:
        text = _compact_text(f"{result_title} {snippet}")
        for pattern in [
            r"\bby\s+([A-Z][A-Za-z0-9 ,'&-]{2,80})(?:[.;|]|\s{2,}|$)",
            r"\bAuthor\s*[:\-]\s*([A-Z][A-Za-z0-9 ,'&-]{2,80})(?:[.;|]|\s{2,}|$)",
        ]:
            match = re.search(pattern, text)
            if match:
                return clean_author_name(match.group(1))
        return ""
