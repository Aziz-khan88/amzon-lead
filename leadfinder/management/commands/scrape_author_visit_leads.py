from __future__ import annotations

import csv
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from django.conf import settings
from django.core.management.base import BaseCommand
from email_validator import EmailNotValidError, validate_email

from leadfinder.services.amazon.amazon_url_parser import extract_asin, normalize_amazon_book_url
from leadfinder.services.crawl.contact_regex import extract_emails, extract_phones
from leadfinder.services.crawl.extract_links import extract_links
from leadfinder.services.crawl.extract_text import extract_page_title, extract_visible_text
from leadfinder.services.crawl.safe_fetch import safe_fetch
from leadfinder.utils.normalize import normalize_text
from leadfinder.utils.url_safety import is_safe_public_url


DISCOVERY_QUERIES = [
    '"children\'s book author" "school visits" "email"',
    '"children\'s book author" "author visits" "email"',
    '"picture book author" "school visits" "email"',
    '"picture book author" "author visits" "contact"',
    '"children\'s author" "school visits" "contact"',
    '"children\'s author" "author visits" "email"',
    '"kids book author" "school visits" "email"',
    '"kids book author" "author visits" "contact"',
    '"children\'s book illustrator" "school visits" "email"',
    '"children\'s book illustrator" "author visits" "contact"',
    '"picture book illustrator" "school visits" "email"',
    '"picture book illustrator" "contact" "author visits"',
    '"elementary school author visit" "children\'s book" "email"',
    '"virtual author visit" "children\'s book" "email"',
    '"book an author visit" "picture book" "email"',
    '"author visit inquiry" "children\'s book"',
    '"school author visits" "picture books" "contact"',
    '"children\'s book author" "booking" "email"',
    '"picture book author" "booking" "email"',
    '"children\'s author" "events" "email"',
    '"children\'s author" "contact me" "picture book"',
    '"picture book author" "contact me"',
    '"children\'s book author" "contact me"',
    '"children\'s author" "speaking" "email"',
    '"author visits" "elementary" "picture book author"',
    '"author visits" "kindergarten" "picture book author"',
    '"author visits" "library" "children\'s author"',
    '"school visits" "children\'s author illustrator"',
    '"children\'s book author website" "email"',
    '"picture book author website" "email"',
]

QUERY_ROLES = [
    "children's book author",
    "children's author",
    "picture book author",
    "kids book author",
    "children's book illustrator",
    "picture book illustrator",
    "author illustrator",
]

QUERY_INTENTS = [
    "school visits",
    "author visits",
    "virtual author visits",
    "library visits",
    "elementary school visits",
    "booking",
    "speaking",
    "events",
    "contact me",
    "visit inquiry",
]

QUERY_TOPICS = [
    "email",
    "contact",
    "picture book",
    "children's book",
    "elementary",
    "library",
    "teacher",
    "assembly",
    "workshop",
]

OUTPUT_COLUMNS = [
    "author_name",
    "phone_or_email",
    "public_email",
    "public_phone",
    "amazon_book_url",
    "book_title",
    "asin",
    "author_website",
    "contact_page_url",
    "contact_source_url",
    "contact_source_title",
    "contact_confidence",
    "validation_status",
    "validation_notes",
    "discovery_query",
    "amazon_source_url",
    "amazon_source_title",
    "all_source_urls",
]


def build_discovery_queries(limit: int) -> list[str]:
    queries = list(DISCOVERY_QUERIES)
    seen = set(queries)
    for role in QUERY_ROLES:
        for intent in QUERY_INTENTS:
            for topic in QUERY_TOPICS:
                query = f'"{role}" "{intent}" "{topic}"'
                if query not in seen:
                    queries.append(query)
                    seen.add(query)
                if len(queries) >= limit:
                    return queries
    return queries[:limit]

BLOCKED_DOMAINS = {
    "amazon.com",
    "barnesandnoble.com",
    "bookshop.org",
    "booktopia.com.au",
    "booksamillion.com",
    "facebook.com",
    "goodreads.com",
    "instagram.com",
    "kdp.amazon.com",
    "linkedin.com",
    "pinterest.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "youtu.be",
}

BLOCKED_DOMAIN_PARTS = (
    "authormedia",
    "beenverified",
    "bookriot",
    "bookshop",
    "childrensbookmastery",
    "directories",
    "facebook",
    "google",
    "library",
    "peoplefinders",
    "radaris",
    "scholastic.com",
    "spokeo",
    "truepeoplesearch",
    "wikipedia",
    "writer.org",
)

AUTHOR_PAGE_HINTS = (
    "about",
    "author",
    "book",
    "contact",
    "event",
    "media",
    "school",
    "speaking",
    "visit",
)


@dataclass(slots=True)
class AuthorCandidate:
    author_name: str
    public_email: str
    public_phone: str
    author_website: str
    contact_page_url: str
    contact_source_url: str
    contact_source_title: str
    contact_confidence: float
    discovery_query: str
    all_source_urls: set[str]


@dataclass(slots=True)
class AmazonMatch:
    amazon_book_url: str
    asin: str
    book_title: str
    amazon_source_url: str
    amazon_source_title: str


def domain(url: str) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def root_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/"


def blocked_url(url: str) -> bool:
    current = domain(url)
    return current in BLOCKED_DOMAINS or any(part in current for part in BLOCKED_DOMAIN_PARTS)


def compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def clean_name(value: str) -> str:
    text = normalize_text(value)
    text = re.sub(r"\s*[|:–-]\s*.*$", "", text).strip()
    text = re.sub(
        r"\b(Author Visits?|School Visits?|Books?|Contact|About|Home|Official Website|Children s Book Author|Childrens Book Author|Children'?s Book Author|Picture Book Author|Author|Illustrator)\b",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\b(children|childrens|children s|picture book|kids|welcome|primary menu|hi i'?m)\b", "", text, flags=re.I)
    text = re.sub(r"\bs\b$", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -:|")
    return text[:90]


def valid_author_name(name: str) -> bool:
    if not name or len(name) < 5 or len(name) > 90:
        return False
    lowered = name.lower()
    if lowered.startswith(("the ", "info ", "hello ")):
        return False
    if any(
        token in lowered
        for token in [
            "aloud",
            "amazon",
            "authors",
            "children",
            "engaging",
            "flexible",
            "illustration",
            "library",
            "menu",
            "picture",
            "publisher",
            "publishing",
            "school",
            "visit",
            "welcome",
            "willow",
            "writing",
        ]
    ):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'.-]+", name)
    return 2 <= len(words) <= 5


def name_tokens(author_name: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z][A-Za-z'.-]+", author_name or "") if len(token) >= 4]


def page_mentions_children_author(text: str) -> bool:
    lowered = (text or "").lower()
    child = any(token in lowered for token in ["children", "childrens", "children's", "picture book", "kids", "elementary", "school visit", "author visit"])
    author = any(token in lowered for token in ["author", "illustrator", "my books", "book an", "visit", "speaking"])
    return child and author


def author_from_page(result_title: str, page_title: str, html: str, url: str) -> str:
    soup = BeautifulSoup(html or "", "lxml")
    candidates: list[str] = []
    candidates.extend([page_title, result_title])
    for selector in ["h1", "h2"]:
        tag = soup.find(selector)
        if tag:
            candidates.append(tag.get_text(" ", strip=True))
    host = domain(url).split(".")[0]
    if host and "-" not in host and len(host) >= 8:
        spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", host)
        candidates.append(spaced)
    joined_candidates = " | ".join(candidates)
    regexes = [
        r"\bwith\s+([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,3})\b",
        r"\bby\s+([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,3})\b",
        r"(?:Contact|About|Visit|Visits|Website)\s+[-—–:]\s+([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,3})\b",
        r"\b([A-Z][A-Za-z'.-]+\s+[A-Z][A-Za-z'.-]+)\s+(?:Author|Illustrator|Books|Website)\b",
    ]
    for regex in regexes:
        match = re.search(regex, joined_candidates)
        if match:
            cleaned = clean_name(match.group(1))
            if valid_author_name(cleaned):
                return cleaned
    for candidate in candidates:
        cleaned = clean_name(candidate)
        if valid_author_name(cleaned):
            return cleaned
    return ""


def valid_email(email: str) -> bool:
    try:
        validate_email(email, check_deliverability=False)
    except EmailNotValidError:
        return False
    lowered = email.lower()
    if lowered in {"email@address.com", "name@example.com", "yourname@example.com"}:
        return False
    return not any(token in lowered for token in ["example.", "domain.", "privacy@", "sentry", "wixpress"])


def page_paths(url: str) -> list[str]:
    root = root_url(url)
    paths = [
        "",
        "contact",
        "contact-me",
        "about",
        "about-me",
        "author-visits",
        "school-visits",
        "visits",
        "events",
        "books",
        "media",
        "speaking",
    ]
    pages = [url, *[urljoin(root, path) for path in paths]]
    seen: list[str] = []
    for page in pages:
        if page not in seen and is_safe_public_url(page):
            seen.append(page)
    return seen


def looks_author_owned(author_name: str, url: str, page_title: str, text: str) -> bool:
    tokens = name_tokens(author_name)
    if not tokens:
        return False
    d = compact(domain(url))
    title = compact(page_title)
    body_start = compact(text[:2500])
    joined = compact(author_name)
    if joined and (joined in d or joined in title or joined in body_start):
        return True
    if len(tokens) >= 2 and tokens[0] in d and tokens[-1] in d:
        return True
    if tokens[-1] in d and tokens[0] in body_start:
        return True
    return False


def parse_amazon_match(author_name: str, item: dict) -> AmazonMatch | None:
    url = item.get("url") or ""
    asin = extract_asin(url)
    if not asin:
        return None
    title = normalize_text(item.get("title") or "")
    content = normalize_text(item.get("content") or "")
    if compact(author_name) not in compact(f"{title} {content}"):
        return None
    if not page_mentions_children_author(f"{title} {content}"):
        return None
    book_title = re.sub(r"\s*-\s*Amazon\.com.*$", "", title, flags=re.I).strip(" -:|")[:180]
    return AmazonMatch(
        amazon_book_url=normalize_amazon_book_url(url),
        asin=asin,
        book_title=book_title,
        amazon_source_url=url,
        amazon_source_title=title,
    )


class Command(BaseCommand):
    help = "Scrape public author pages and pair validated contacts with Amazon children-book URLs."

    def add_arguments(self, parser):
        parser.add_argument("--target-leads", type=int, default=400)
        parser.add_argument("--output", default="data/scraped_valid_children_author_leads_400.csv")
        parser.add_argument("--max-discovery-queries", type=int, default=len(DISCOVERY_QUERIES))
        parser.add_argument("--max-results", type=int, default=20)
        parser.add_argument("--max-pages-per-site", type=int, default=4)
        parser.add_argument("--no-fetch", action="store_true")
        parser.add_argument("--sleep", type=float, default=0.15)

    def handle(self, *args, **options):
        try:
            from tavily import TavilyClient
        except Exception as exc:
            raise RuntimeError("Install tavily-python before running this command.") from exc

        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            raise RuntimeError("TAVILY_API_KEY is required.")

        client = TavilyClient(api_key)
        target = max(1, min(int(options["target_leads"]), 700))
        max_results = max(1, min(int(options["max_results"]), 20))
        max_pages = max(1, min(int(options["max_pages_per_site"]), 8))
        sleep_seconds = max(0.0, float(options["sleep"]))
        output = Path(options["output"])
        if not output.is_absolute():
            output = Path(settings.BASE_DIR) / output
        output.parent.mkdir(parents=True, exist_ok=True)

        authors: dict[str, AuthorCandidate] = {}
        queries = build_discovery_queries(max(1, int(options["max_discovery_queries"])))
        for query in queries:
            self.stdout.write(f"Finding author sites: {query}")
            try:
                response = client.search(query=query, search_depth="advanced", max_results=max_results)
            except Exception as exc:
                self.stderr.write(f"Discovery failed: {exc}")
                continue
            for item in response.get("results", []):
                if len(authors) >= target * 3:
                    break
                url = item.get("url") or ""
                if not url or blocked_url(url):
                    continue
                candidate = self.scrape_author_site(
                    url=url,
                    result_title=item.get("title") or "",
                    result_content=item.get("content") or "",
                    discovery_query=query,
                    max_pages=max_pages,
                    no_fetch=bool(options["no_fetch"]),
                )
                if not candidate:
                    continue
                key = compact(candidate.author_name)
                authors.setdefault(key, candidate)
            time.sleep(sleep_seconds)

        self.stdout.write(f"Found {len(authors)} contactable author-site candidates.")

        rows: list[dict[str, object]] = []
        seen_contact: set[str] = set()
        for index, author in enumerate(authors.values(), start=1):
            if len(rows) >= target:
                break
            self.stdout.write(f"[{index}/{len(authors)}] Finding Amazon URL: {author.author_name}")
            amazon = self.find_amazon_match(client, author)
            if not amazon:
                continue
            contact_key = (author.public_email or author.public_phone).lower()
            if not contact_key or contact_key in seen_contact:
                continue
            seen_contact.add(contact_key)
            rows.append(
                {
                    "author_name": author.author_name,
                    "phone_or_email": author.public_email or author.public_phone,
                    "public_email": author.public_email,
                    "public_phone": author.public_phone,
                    "amazon_book_url": amazon.amazon_book_url,
                    "book_title": amazon.book_title,
                    "asin": amazon.asin,
                    "author_website": author.author_website,
                    "contact_page_url": author.contact_page_url,
                    "contact_source_url": author.contact_source_url,
                    "contact_source_title": author.contact_source_title,
                    "contact_confidence": author.contact_confidence,
                    "validation_status": "needs_manual_review",
                    "validation_notes": "Contact is from a public author-owned children-book/author-visit page. Amazon URL is from public search-result metadata and matches the author. Manual verification before outreach.",
                    "discovery_query": author.discovery_query,
                    "amazon_source_url": amazon.amazon_source_url,
                    "amazon_source_title": amazon.amazon_source_title,
                    "all_source_urls": "; ".join(sorted(author.all_source_urls | {amazon.amazon_source_url})),
                }
            )
            self.write_rows(output, rows)

        self.write_rows(output, rows)
        self.stdout.write(self.style.SUCCESS(f"Exported {len(rows)} leads to {output}"))

    def scrape_author_site(
        self,
        url: str,
        result_title: str,
        result_content: str,
        discovery_query: str,
        max_pages: int,
        no_fetch: bool = False,
    ) -> AuthorCandidate | None:
        combined_text = result_content
        source_urls: set[str] = {url}
        first_html = ""
        best_title = result_title
        contact_source_url = ""
        contact_page_url = ""
        public_email = ""
        public_phone = ""

        snippet_emails = [email for email in extract_emails(f"{result_title}\n{result_content}") if valid_email(email)]
        snippet_phones = extract_phones(f"{result_title}\n{result_content}", require_context=True)
        if snippet_emails or snippet_phones:
            public_email = snippet_emails[0] if snippet_emails else ""
            public_phone = snippet_phones[0] if snippet_phones else ""
            contact_source_url = url

        pages_to_fetch = [] if no_fetch else page_paths(url)[:max_pages]
        for page in pages_to_fetch:
            if blocked_url(page):
                continue
            fetched = safe_fetch(page)
            if not fetched or fetched.status_code >= 400:
                continue
            source_urls.add(fetched.url)
            title = extract_page_title(fetched.html) or result_title
            best_title = title or best_title
            first_html = first_html or fetched.html
            text = extract_visible_text(fetched.html)
            combined_text = f"{combined_text}\n{text}"[:40000]
            emails = [email for email in extract_emails(text) if valid_email(email)]
            phones = extract_phones(text, require_context=True)
            if (emails or phones) and not contact_source_url:
                public_email = emails[0] if emails else ""
                public_phone = phones[0] if phones else ""
                contact_source_url = fetched.url
                if "contact" in fetched.url.lower():
                    contact_page_url = fetched.url
            for link in extract_links(fetched.html, fetched.url)[:30]:
                source_urls.add(link)

        if not contact_source_url or not page_mentions_children_author(combined_text):
            return None
        author_name = author_from_page(result_title, best_title, first_html, url)
        if not valid_author_name(author_name):
            return None
        if no_fetch:
            packed_name = compact(author_name)
            if packed_name not in compact(best_title) and packed_name not in compact(domain(url)):
                return None
        if not looks_author_owned(author_name, url, best_title, combined_text):
            return None
        return AuthorCandidate(
            author_name=author_name,
            public_email=public_email,
            public_phone=public_phone,
            author_website=root_url(url),
            contact_page_url=contact_page_url,
            contact_source_url=contact_source_url,
            contact_source_title=best_title,
            contact_confidence=0.82 if contact_page_url else 0.74,
            discovery_query=discovery_query,
            all_source_urls=source_urls,
        )

    def find_amazon_match(self, client, author: AuthorCandidate) -> AmazonMatch | None:
        queries = [
            f'site:amazon.com/dp "{author.author_name}" "children"',
            f'site:amazon.com/dp "{author.author_name}" "picture book"',
            f'amazon.com/dp "{author.author_name}" "children book"',
            f'amazon.com/dp "{author.author_name}" "author"',
        ]
        for query in queries:
            try:
                response = client.search(query=query, search_depth="advanced", max_results=8)
            except Exception as exc:
                self.stderr.write(f"Amazon lookup failed for {author.author_name}: {exc}")
                continue
            for item in response.get("results", []):
                match = parse_amazon_match(author.author_name, item)
                if match:
                    return match
            time.sleep(0.1)
        return None

    def write_rows(self, output: Path, rows: list[dict[str, object]]) -> None:
        with output.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
