from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from django.conf import settings
from django.core.management.base import BaseCommand

from leadfinder.services.amazon.amazon_url_parser import extract_asin, normalize_amazon_book_url
from leadfinder.services.crawl.contact_regex import extract_emails, extract_phones
from leadfinder.services.crawl.extract_links import extract_links
from leadfinder.services.crawl.extract_text import extract_page_title, extract_visible_text
from leadfinder.services.crawl.safe_fetch import safe_fetch
from leadfinder.services.search import get_search_provider
from leadfinder.utils.normalize import normalize_text
from leadfinder.utils.url_safety import is_safe_public_url


SEARCH_QUERIES = [
    '"children\'s book author" "Buy on Amazon" "Contact"',
    '"children\'s book author" "Amazon" "email"',
    '"picture book author" "Amazon" "contact"',
    '"kids book author" "Amazon" "contact"',
    '"self-published children\'s book author" "Amazon" "contact"',
    '"independent children\'s author" "Amazon" "email"',
    '"children\'s author" "available on Amazon" "contact"',
    '"picture book" "Buy on Amazon" "author" "email"',
    '"children\'s book" "Buy Now" "Amazon" "Contact Me"',
    '"children\'s book author" "school visits" "Amazon" "email"',
    '"picture book author" "school visits" "contact" "Amazon"',
    '"children\'s author" "booking" "email" "Amazon"',
    '"children\'s book illustrator author" "Amazon" "contact"',
    '"Christian children\'s book author" "Amazon" "contact"',
    '"bedtime story" "children\'s book author" "Amazon" "contact"',
    '"rhyming children\'s book" "Amazon" "contact author"',
    '"social emotional learning" "picture book author" "Amazon" "contact"',
    '"diverse children\'s book author" "Amazon" "email"',
    '"new children\'s book" "Amazon" "author website" "contact"',
    '"children\'s book series" "Amazon" "contact author"',
]

AUTHOR_NOISE = [
    "home",
    "books",
    "contact",
    "official website",
    "children's book author",
    "childrens book author",
    "picture book author",
    "author and illustrator",
    "author",
    "illustrator",
    "welcome",
]

BAD_EMAIL_PARTS = {
    "example.",
    "domain.",
    "sentry",
    "wixpress",
    "schema",
    "privacy@",
    "support@wix",
}

RETAIL_OR_SOCIAL_HOSTS = (
    "amazon.",
    "barnesandnoble.",
    "goodreads.",
    "youtube.",
    "youtu.be",
    "facebook.",
    "instagram.",
    "tiktok.",
    "linkedin.",
    "x.com",
    "twitter.",
)

OUTPUT_COLUMNS = [
    "author_name",
    "public_email",
    "public_phone",
    "amazon_book_url",
    "asin",
    "author_website",
    "contact_page_url",
    "contact_source_url",
    "contact_confidence",
    "book_title",
    "lead_type",
    "validation_status",
    "validation_notes",
    "search_query",
    "search_result_title",
    "all_source_urls",
]


@dataclass(slots=True)
class HarvestCandidate:
    author_name: str
    public_email: str
    public_phone: str
    amazon_book_url: str
    asin: str
    author_website: str
    contact_page_url: str
    contact_source_url: str
    contact_confidence: float
    book_title: str
    lead_type: str
    validation_notes: str
    search_query: str
    search_result_title: str
    all_source_urls: set[str] = field(default_factory=set)


def host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def site_root(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/"


def is_author_site_url(url: str) -> bool:
    parsed_host = host(url)
    if not parsed_host:
        return False
    return not any(token in parsed_host for token in RETAIL_OR_SOCIAL_HOSTS)


def candidate_pages(url: str) -> list[str]:
    root = site_root(url)
    paths = ["", "contact", "contact-us", "about", "about-me", "books", "media", "school-visits", "events"]
    seen: list[str] = []
    for page in [url, *[urljoin(root, path) for path in paths]]:
        if page not in seen and is_safe_public_url(page):
            seen.append(page)
    return seen


def amazon_urls_from_text_and_links(text: str, links: list[str]) -> list[str]:
    urls = list(links)
    urls.extend(re.findall(r"https?://(?:www\.)?amazon\.[^\s\"'<>]+", text or "", flags=re.I))
    normalized: list[str] = []
    for url in urls:
        if "amazon." not in url.lower():
            continue
        asin = extract_asin(url)
        if not asin:
            continue
        clean = normalize_amazon_book_url(url)
        if clean not in normalized:
            normalized.append(clean)
    return normalized


def mailto_emails(html: str) -> list[str]:
    soup = BeautifulSoup(html or "", "lxml")
    emails: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href.lower().startswith("mailto:"):
            continue
        email = href[7:].split("?", 1)[0].strip().lower()
        if email and email not in emails:
            emails.append(email)
    return emails


def clean_email(email: str) -> str:
    return email.strip().strip(".,;:()[]{}<>").lower()


def clean_author_name(value: str) -> str:
    text = normalize_text(value)
    text = re.sub(r"\s*[|:–-]\s*.*$", "", text).strip()
    for token in AUTHOR_NOISE:
        text = re.sub(re.escape(token), "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -|:")
    return text[:90]


def author_from_page(result_title: str, page_title: str, html: str) -> str:
    soup = BeautifulSoup(html or "", "lxml")
    candidates: list[str] = []
    for selector in ["h1", "h2"]:
        tag = soup.find(selector)
        if tag:
            candidates.append(tag.get_text(" ", strip=True))
    candidates.extend([page_title, result_title])
    for candidate in candidates:
        name = clean_author_name(candidate)
        words = re.findall(r"[A-Za-z][A-Za-z'.-]+", name)
        if 1 <= len(words) <= 5 and len(name) >= 4:
            return name
    return ""


def likely_children_author_page(text: str, links: list[str]) -> bool:
    haystack = " ".join([text[:6000], " ".join(links[:50])]).lower()
    has_book_signal = any(
        token in haystack
        for token in [
            "children's book",
            "childrens book",
            "children book",
            "picture book",
            "kids book",
            "school visit",
            "bedtime story",
        ]
    )
    has_author_signal = any(token in haystack for token in ["author", "illustrator", "my books", "book series"])
    return has_book_signal and has_author_signal


def valid_email(email: str) -> bool:
    if not email or "@" not in email:
        return False
    lowered = email.lower()
    return not any(part in lowered for part in BAD_EMAIL_PARTS)


def row_key(candidate: HarvestCandidate) -> str:
    if candidate.public_email:
        return candidate.public_email
    if candidate.public_phone:
        return candidate.public_phone
    return f"{candidate.asin}:{candidate.author_name.lower()}"


class Command(BaseCommand):
    help = "Harvest source-linked children's author leads from public author websites that link to Amazon books."

    def add_arguments(self, parser):
        parser.add_argument("--provider", default="tavily", choices=["tavily", "ddgs"])
        parser.add_argument("--target-leads", type=int, default=700)
        parser.add_argument("--output", default="data/author_site_amazon_contact_leads.csv")
        parser.add_argument("--max-queries", type=int, default=len(SEARCH_QUERIES))
        parser.add_argument("--max-results", type=int, default=10)
        parser.add_argument("--max-pages-per-site", type=int, default=4)

    def handle(self, *args, **options):
        provider = get_search_provider(options["provider"])
        target = max(1, min(options["target_leads"], 700))
        max_queries = max(1, min(options["max_queries"], len(SEARCH_QUERIES)))
        max_results = max(1, min(options["max_results"], 20))
        max_pages = max(1, min(options["max_pages_per_site"], 8))
        output = Path(options["output"])
        if not output.is_absolute():
            output = Path(settings.BASE_DIR) / output
        output.parent.mkdir(parents=True, exist_ok=True)

        leads: list[HarvestCandidate] = []
        seen_pages: set[str] = set()
        seen_keys: set[str] = set()

        for query in SEARCH_QUERIES[:max_queries]:
            if len(leads) >= target:
                break
            self.stdout.write(f"Searching: {query}")
            results = provider.search(query, max_results=max_results)
            for result in results:
                if len(leads) >= target:
                    break
                if not is_author_site_url(result.url):
                    continue
                root = site_root(result.url)
                if root in seen_pages:
                    continue
                seen_pages.add(root)

                combined_text = ""
                combined_links: list[str] = []
                source_urls: set[str] = set()
                source_html = ""
                contact_page_url = ""
                source_url = ""
                page_title = result.title

                for page_url in candidate_pages(result.url)[:max_pages]:
                    fetched = safe_fetch(page_url)
                    if not fetched or fetched.status_code >= 400:
                        continue
                    source_urls.add(fetched.url)
                    source_url = source_url or fetched.url
                    title = extract_page_title(fetched.html)
                    page_title = title or page_title
                    source_html = source_html or fetched.html
                    text = extract_visible_text(fetched.html)
                    links = extract_links(fetched.html, fetched.url)
                    combined_text = f"{combined_text}\n{text}"[:30000]
                    for link in links:
                        if link not in combined_links:
                            combined_links.append(link)
                    if "contact" in fetched.url.lower() and not contact_page_url:
                        contact_page_url = fetched.url

                if not combined_text or not likely_children_author_page(combined_text, combined_links):
                    continue

                amazon_urls = amazon_urls_from_text_and_links(combined_text, combined_links)
                if not amazon_urls:
                    continue

                emails = [clean_email(email) for email in [*extract_emails(combined_text), *mailto_emails(source_html)]]
                emails = [email for index, email in enumerate(emails) if valid_email(email) and email not in emails[:index]]
                phones = extract_phones(combined_text, require_context=True)
                if not emails and not phones:
                    continue

                author_name = author_from_page(result.title, page_title, source_html)
                if not author_name:
                    continue

                for amazon_url in amazon_urls[:2]:
                    asin = extract_asin(amazon_url) or ""
                    candidate = HarvestCandidate(
                        author_name=author_name,
                        public_email=emails[0] if emails else "",
                        public_phone=phones[0] if phones else "",
                        amazon_book_url=amazon_url,
                        asin=asin,
                        author_website=root,
                        contact_page_url=contact_page_url,
                        contact_source_url=contact_page_url or source_url or result.url,
                        contact_confidence=0.72 if contact_page_url else 0.65,
                        book_title="",
                        lead_type="children_book_author_or_illustrator",
                        validation_notes="Public author site contains children/picture-book signals, public contact, and Amazon book link. Manual review before outreach.",
                        search_query=query,
                        search_result_title=result.title,
                        all_source_urls=source_urls | {result.url},
                    )
                    key = row_key(candidate)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    leads.append(candidate)
                    self.stdout.write(f"  + {candidate.author_name} | {candidate.public_email or candidate.public_phone}")
                    if len(leads) >= target:
                        break

        with output.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            for lead in leads:
                writer.writerow(
                    {
                        "author_name": lead.author_name,
                        "public_email": lead.public_email,
                        "public_phone": lead.public_phone,
                        "amazon_book_url": lead.amazon_book_url,
                        "asin": lead.asin,
                        "author_website": lead.author_website,
                        "contact_page_url": lead.contact_page_url,
                        "contact_source_url": lead.contact_source_url,
                        "contact_confidence": lead.contact_confidence,
                        "book_title": lead.book_title,
                        "lead_type": lead.lead_type,
                        "validation_status": "needs_manual_review",
                        "validation_notes": lead.validation_notes,
                        "search_query": lead.search_query,
                        "search_result_title": lead.search_result_title,
                        "all_source_urls": "; ".join(sorted(lead.all_source_urls)),
                    }
                )

        self.stdout.write(self.style.SUCCESS(f"Exported {len(leads)} leads to {output}"))
