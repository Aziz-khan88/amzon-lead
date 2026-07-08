from __future__ import annotations

import csv
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand
from email_validator import EmailNotValidError, validate_email

from leadfinder.services.amazon.amazon_url_parser import extract_asin, normalize_amazon_book_url
from leadfinder.services.crawl.contact_regex import extract_emails, extract_phones
from leadfinder.services.crawl.extract_links import extract_links
from leadfinder.services.crawl.extract_text import extract_page_title, extract_visible_text
from leadfinder.services.crawl.safe_fetch import safe_fetch
from leadfinder.utils.normalize import normalize_text


CHILDREN_BOOK_TERMS = [
    "children picture book",
    "kids picture book",
    "bedtime story children book",
    "rhyming children book",
    "animal picture book",
    "preschool picture book",
    "kindergarten picture book",
    "early reader picture book",
    "social emotional learning picture book",
    "diverse children book",
    "christian children book",
    "bilingual children book",
    "self published children book",
    "independent children author",
    "children book series",
    "illustrated children storybook",
    "children book illustration",
    "kids bedtime story",
    "toddler picture book",
    "new children picture book",
    "children fantasy picture book",
    "children adventure picture book",
    "children poetry picture book",
    "emotions picture book",
    "school readiness picture book",
]

AMAZON_DISCOVERY_PATTERNS = [
    'site:amazon.com/dp {term} by author',
    'site:amazon.com/dp "{term}" "by"',
    'site:amazon.com/dp "{term}" paperback author',
    'amazon.com/dp "{term}" "Author"',
]

CONTACT_QUERY_PATTERNS = [
    '"{author}" "{title}" email contact',
    '"{author}" "{title}" author website',
    '"{author}" children book author email',
    '"{author}" picture book author contact',
    '"{author}" school visits email',
    '"{author}" author contact',
]

OUTPUT_COLUMNS = [
    "author_name",
    "phone_or_email",
    "public_email",
    "public_phone",
    "amazon_book_url",
    "book_title",
    "asin",
    "contact_source_url",
    "contact_source_title",
    "contact_confidence",
    "validation_status",
    "validation_notes",
    "amazon_source_url",
    "amazon_source_title",
    "contact_query",
    "all_source_urls",
]

BAD_AUTHOR_TOKENS = {
    "amazon",
    "audible",
    "book series",
    "paperback",
    "kindle",
    "hardcover",
    "edition",
    "children's books",
    "kids books",
    "publishing",
    "publisher",
    "press",
    "books",
    "calendar",
    "collection",
    "series",
    "world",
}

BLOCKED_CONTACT_DOMAINS = {
    "amazon.com",
    "awesomebooks.com",
    "kdp.amazon.com",
    "goodreads.com",
    "barnesandnoble.com",
    "beenverified.com",
    "biblio.com",
    "books.google.com",
    "booktopia.com.au",
    "booksamillion.com",
    "christianbook.com",
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "x.com",
    "twitter.com",
    "linkedin.com",
    "pubmed.ncbi.nlm.nih.gov",
    "whitepages.com",
    "wordpress.com",
}

BLOCKED_DOMAIN_PARTS = (
    ".cdn.",
    "digitaloceanspaces.com",
    "review",
    "news",
    "chronicle",
    "peoplefinders",
    "radaris",
    "spokeo",
    "truepeoplesearch",
)

OFFICIAL_PAGE_HINTS = (
    "about",
    "author",
    "book",
    "contact",
    "school",
    "visit",
    "media",
    "press",
)


@dataclass(slots=True)
class BookCandidate:
    title: str
    author_name: str
    amazon_book_url: str
    asin: str
    amazon_source_url: str
    amazon_source_title: str
    amazon_source_snippet: str


@dataclass(slots=True)
class ContactMatch:
    public_email: str = ""
    public_phone: str = ""
    source_url: str = ""
    source_title: str = ""
    confidence: float = 0.0
    contact_query: str = ""
    all_source_urls: set[str] = field(default_factory=set)


def registered_domain(url: str) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def blocked_contact_url(url: str) -> bool:
    domain = registered_domain(url)
    return domain in BLOCKED_CONTACT_DOMAINS or any(part in domain for part in BLOCKED_DOMAIN_PARTS)


def compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def author_tokens(author_name: str) -> list[str]:
    return [token.lower() for token in re.findall(r"[A-Za-z][A-Za-z'.-]+", author_name or "") if len(token) >= 4]


def text_mentions_author(author_name: str, *values: str) -> bool:
    tokens = author_tokens(author_name)
    if not tokens:
        return False
    text = " ".join(values).lower()
    compact_text = compact(text)
    compact_author = compact(author_name)
    if compact_author and compact_author in compact_text:
        return True
    return sum(1 for token in tokens if token in text or token in compact_text) >= min(2, len(tokens))


def domain_or_title_looks_author_owned(author_name: str, url: str, source_title: str) -> bool:
    tokens = author_tokens(author_name)
    if not tokens:
        return False
    domain = compact(registered_domain(url))
    title = compact(source_title)
    joined = compact(author_name)
    if joined and joined in domain:
        return True
    if len(tokens) >= 2 and tokens[0] in domain and tokens[-1] in domain:
        return True
    if len(tokens[-1]) >= 5 and tokens[-1] in domain:
        return True
    return joined and joined in title


def text_mentions_children_book(text: str) -> bool:
    lowered = (text or "").lower()
    return any(
        token in lowered
        for token in [
            "children",
            "childrens",
            "children's",
            "picture book",
            "kids",
            "toddler",
            "preschool",
            "bedtime",
            "storybook",
        ]
    )


def clean_title(value: str) -> str:
    title = normalize_text(value)
    title = re.sub(r"\s*-\s*Amazon\.com.*$", "", title, flags=re.I)
    title = re.sub(r"\s*:\s*Amazon\.com.*$", "", title, flags=re.I)
    title = re.sub(r"\s*\|\s*Amazon.*$", "", title, flags=re.I)
    return title.strip(" -:|")[:180]


def clean_author(value: str) -> str:
    author = normalize_text(value)
    author = re.sub(r"\s*\([^)]*\)", "", author)
    author = re.sub(r"\b(Author|Illustrator|Editor|Creator)\b", "", author, flags=re.I)
    author = re.sub(r"[,;/|].*$", "", author)
    author = re.sub(r"\s+", " ", author).strip(" .-:|")
    return author[:90]


def parse_book_candidate(title: str, url: str, snippet: str) -> BookCandidate | None:
    asin = extract_asin(url)
    if not asin:
        return None
    text = f"{title} {snippet}"
    author = ""
    by_match = re.search(r"\bby\s+([A-Z][A-Za-z0-9 .,'&-]{2,90}?)(?:\s+\((?:Author|Illustrator)\)|[.;|#\n\r]|$)", text)
    if by_match:
        author = clean_author(by_match.group(1))
    title_value = clean_title(title)
    if " by " in title_value.lower():
        parts = re.split(r"\s+by\s+", title_value, maxsplit=1, flags=re.I)
        title_value = clean_title(parts[0])
        author = author or clean_author(parts[1])
    if not author:
        return None
    if not valid_author_name(author):
        return None
    if not text_mentions_children_book(text):
        return None
    return BookCandidate(
        title=title_value,
        author_name=author,
        amazon_book_url=normalize_amazon_book_url(url),
        asin=asin,
        amazon_source_url=url,
        amazon_source_title=title,
        amazon_source_snippet=snippet,
    )


def valid_author_name(name: str) -> bool:
    normalized = normalize_text(name)
    if len(normalized) < 5 or len(normalized) > 90:
        return False
    lowered = normalized.lower()
    if any(token in lowered for token in BAD_AUTHOR_TOKENS):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'.-]+", normalized)
    return 2 <= len(words) <= 5


def valid_email(email: str) -> bool:
    try:
        validate_email(email, check_deliverability=False)
    except EmailNotValidError:
        return False
    lowered = email.lower()
    return not any(token in lowered for token in ["example.", "domain.", "sentry", "privacy@", "support@"])


def extract_contact_from_text(author_name: str, title: str, text: str, url: str, source_title: str) -> ContactMatch | None:
    if blocked_contact_url(url):
        return None
    url_text = f"{url} {source_title}".lower()
    if not any(hint in url_text for hint in OFFICIAL_PAGE_HINTS):
        return None
    if not text_mentions_author(author_name, url, source_title, text):
        return None
    if not domain_or_title_looks_author_owned(author_name, url, source_title):
        return None
    emails = [email for email in extract_emails(text) if valid_email(email)]
    phones = extract_phones(text, require_context=True)
    if not emails and not phones:
        return None
    mentions_title = compact(title)[:24] and compact(title)[:24] in compact(text)
    return ContactMatch(
        public_email=emails[0] if emails else "",
        public_phone=phones[0] if phones else "",
        source_url=url,
        source_title=source_title,
        confidence=0.78 if mentions_title else 0.68,
        all_source_urls={url},
    )


class Command(BaseCommand):
    help = "Pull validated children's-book author leads with Tavily search and public source checks."

    def add_arguments(self, parser):
        parser.add_argument("--target-leads", type=int, default=500)
        parser.add_argument("--output", default="data/tavily_validated_500_children_book_author_leads.csv")
        parser.add_argument("--max-discovery-queries", type=int, default=120)
        parser.add_argument("--max-results", type=int, default=10)
        parser.add_argument("--max-contact-pages", type=int, default=2)
        parser.add_argument("--sleep", type=float, default=0.2)

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
        max_contact_pages = max(0, min(int(options["max_contact_pages"]), 5))
        sleep_seconds = max(0.0, float(options["sleep"]))

        output = Path(options["output"])
        if not output.is_absolute():
            output = Path(settings.BASE_DIR) / output
        output.parent.mkdir(parents=True, exist_ok=True)

        discovery_queries: list[str] = []
        for term in CHILDREN_BOOK_TERMS:
            for pattern in AMAZON_DISCOVERY_PATTERNS:
                discovery_queries.append(pattern.format(term=term))
        discovery_queries = discovery_queries[: max(1, int(options["max_discovery_queries"]))]

        books: dict[str, BookCandidate] = {}
        for query in discovery_queries:
            if len(books) >= target * 4:
                break
            self.stdout.write(f"Discovering books: {query}")
            try:
                response = client.search(query=query, search_depth="advanced", max_results=max_results)
            except Exception as exc:
                self.stderr.write(f"Discovery query failed: {exc}")
                continue
            for item in response.get("results", []):
                candidate = parse_book_candidate(
                    item.get("title") or "",
                    item.get("url") or "",
                    item.get("content") or "",
                )
                if candidate:
                    books.setdefault(candidate.asin, candidate)
            time.sleep(sleep_seconds)

        self.stdout.write(f"Discovered {len(books)} unique author/book candidates.")

        leads: list[dict[str, object]] = []
        seen_contacts: set[str] = set()
        for index, book in enumerate(books.values(), start=1):
            if len(leads) >= target:
                break
            self.stdout.write(f"[{index}/{len(books)}] Contact search: {book.author_name}")
            contact = self.find_contact(client, book, max_results=max_results, max_contact_pages=max_contact_pages)
            if not contact:
                continue
            key = (contact.public_email or contact.public_phone).lower()
            if not key or key in seen_contacts:
                continue
            seen_contacts.add(key)
            phone_or_email = contact.public_email or contact.public_phone
            leads.append(
                {
                    "author_name": book.author_name,
                    "phone_or_email": phone_or_email,
                    "public_email": contact.public_email,
                    "public_phone": contact.public_phone,
                    "amazon_book_url": book.amazon_book_url,
                    "book_title": book.title,
                    "asin": book.asin,
                    "contact_source_url": contact.source_url,
                    "contact_source_title": contact.source_title,
                    "contact_confidence": contact.confidence,
                    "validation_status": "needs_manual_review",
                    "validation_notes": "Amazon URL came from public search result metadata. Contact source mentions the author and exposes a public email/phone. Manually verify before outreach.",
                    "amazon_source_url": book.amazon_source_url,
                    "amazon_source_title": book.amazon_source_title,
                    "contact_query": contact.contact_query,
                    "all_source_urls": "; ".join(sorted(contact.all_source_urls | {book.amazon_source_url})),
                }
            )

        with output.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            writer.writerows(leads)

        self.stdout.write(self.style.SUCCESS(f"Exported {len(leads)} validated leads to {output}"))

    def find_contact(
        self,
        client,
        book: BookCandidate,
        max_results: int,
        max_contact_pages: int,
    ) -> ContactMatch | None:
        for query_template in CONTACT_QUERY_PATTERNS:
            query = query_template.format(author=book.author_name, title=book.title[:80])
            try:
                response = client.search(query=query, search_depth="advanced", max_results=max_results)
            except Exception as exc:
                self.stderr.write(f"Contact query failed for {book.author_name}: {exc}")
                continue
            pages_checked = 0
            for item in response.get("results", []):
                if pages_checked >= max_contact_pages:
                    break
                url = item.get("url") or ""
                if blocked_contact_url(url):
                    continue
                fetched = safe_fetch(url)
                if not fetched or fetched.status_code >= 400:
                    continue
                pages_checked += 1
                page_title = extract_page_title(fetched.html) or item.get("title") or ""
                text = extract_visible_text(fetched.html)
                match = extract_contact_from_text(book.author_name, book.title, f"{page_title}\n{text}", fetched.url, page_title)
                if match:
                    match.contact_query = query
                    links = extract_links(fetched.html, fetched.url)
                    match.all_source_urls.update(link for link in links[:20] if link.startswith(("http://", "https://")))
                    return match
        return None
