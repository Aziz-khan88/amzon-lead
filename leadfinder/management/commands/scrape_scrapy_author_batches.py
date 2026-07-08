from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import scrapy
from django.conf import settings
from django.core.management.base import BaseCommand
from email_validator import EmailNotValidError, validate_email
from scrapy.crawler import CrawlerProcess
from scrapy.exceptions import DropItem

from leadfinder.services.amazon.amazon_url_parser import extract_asin, normalize_amazon_book_url
from leadfinder.services.crawl.contact_regex import extract_emails, extract_phones
from leadfinder.utils.normalize import normalize_text


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

LOG_COLUMNS = ["timestamp_utc", "event", "batch", "total_rows", "message"]


@dataclass(slots=True)
class SeedLead:
    author_name: str
    public_email: str
    public_phone: str
    amazon_book_url: str
    book_title: str
    asin: str
    author_website: str
    contact_page_url: str
    discovery_query: str

DISCOVERY_QUERIES = [
    '"children\'s book author" "school visits" "amazon"',
    '"children\'s book author" "author visits" "amazon"',
    '"picture book author" "school visits" "amazon"',
    '"picture book author" "author visits" "amazon"',
    '"children\'s author" "school visits" "buy on amazon"',
    '"children\'s author" "contact" "amazon"',
    '"picture book illustrator" "school visits" "amazon"',
    '"children\'s book illustrator" "contact" "amazon"',
    '"kids book author" "school visits" "amazon"',
    '"author visits" "children\'s book" "amazon"',
    '"virtual author visit" "children\'s book" "amazon"',
    '"library visits" "children\'s author" "amazon"',
    '"children\'s author" "books" "amazon" "email"',
    '"picture book author" "books" "amazon" "email"',
]

ROLE_TERMS = [
    "children's book author",
    "children's author",
    "picture book author",
    "kids book author",
    "children's book illustrator",
    "picture book illustrator",
]

INTENT_TERMS = [
    "school visits",
    "author visits",
    "virtual visits",
    "library visits",
    "contact",
    "books",
]

TOPIC_TERMS = ["amazon", "buy on amazon", "bookshop", "email", "contact"]

BLOCKED_DOMAINS = {
    "amazon.com",
    "barnesandnoble.com",
    "bing.com",
    "bookshop.org",
    "duckduckgo.com",
    "facebook.com",
    "goodreads.com",
    "instagram.com",
    "linkedin.com",
    "pinterest.com",
    "tiktok.com",
    "x.com",
    "youtube.com",
    "youtu.be",
}

BLOCKED_DOMAIN_PARTS = (
    "authormedia",
    "beenverified",
    "bookriot",
    "childrensbookmastery",
    "peoplefinders",
    "radaris",
    "scholastic.com",
    "spokeo",
    "truepeoplesearch",
    "wikipedia",
)

AUTHOR_HINTS = (
    "author",
    "illustrator",
    "picture book",
    "children",
    "school visit",
    "author visit",
    "books",
)

FOLLOW_HINTS = (
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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def domain(url: str) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def root_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/"


def blocked_url(url: str) -> bool:
    host = domain(url)
    return not host or host in BLOCKED_DOMAINS or any(part in host for part in BLOCKED_DOMAIN_PARTS)


def valid_email(email: str) -> bool:
    try:
        validate_email(email, check_deliverability=False)
    except EmailNotValidError:
        return False
    lowered = email.lower()
    if lowered in {"email@address.com", "name@example.com", "yourname@example.com"}:
        return False
    return not any(token in lowered for token in ["example.", "domain.", "privacy@", "sentry", "wixpress"])


def clean_author_name(value: str) -> str:
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
    bad_tokens = [
        "aloud",
        "amazon",
        "authors",
        "bookshop",
        "children",
        "library",
        "menu",
        "publisher",
        "publishing",
        "school",
        "visit",
        "welcome",
        "willow",
        "writing",
    ]
    if any(token in lowered for token in bad_tokens):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'.-]+", name)
    return 2 <= len(words) <= 5


def author_from_page(title: str, heading: str, url: str) -> str:
    candidates = [title, heading]
    host = domain(url).split(".")[0].replace("-", " ")
    if host and len(host) >= 8:
        candidates.append(host)
    joined = " | ".join(candidates)
    regexes = [
        r"\bwith\s+([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,3})\b",
        r"\bby\s+([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,3})\b",
        r"(?:Contact|About|Visit|Visits|Website)\s+[-—–:]\s+([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,3})\b",
        r"\b([A-Z][A-Za-z'.-]+\s+[A-Z][A-Za-z'.-]+)\s+(?:Author|Illustrator|Books|Website)\b",
    ]
    for regex in regexes:
        match = re.search(regex, joined)
        if match:
            name = clean_author_name(match.group(1))
            if valid_author_name(name):
                return name
    for candidate in candidates:
        name = clean_author_name(candidate)
        if valid_author_name(name):
            return name
    return ""


def page_has_author_context(text: str) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in AUTHOR_HINTS) and (
        "children" in lowered or "picture book" in lowered or "kids" in lowered
    )


def amazon_links_from_response(response: scrapy.http.Response) -> list[str]:
    links = response.css("a::attr(href)").getall()
    text_urls = re.findall(r"https?://(?:www\.)?amazon\.[^\s\"'<>]+", response.text, flags=re.I)
    found: list[str] = []
    for url in [*links, *text_urls]:
        absolute = urljoin(response.url, url)
        if "amazon." not in absolute.lower():
            continue
        asin = extract_asin(absolute)
        if not asin:
            continue
        normalized = normalize_amazon_book_url(absolute)
        if normalized not in found:
            found.append(normalized)
    return found


def search_queries(limit: int) -> list[str]:
    if limit <= 0:
        return []
    queries = list(DISCOVERY_QUERIES)
    seen = set(queries)
    for role in ROLE_TERMS:
        for intent in INTENT_TERMS:
            for topic in TOPIC_TERMS:
                query = f'"{role}" "{intent}" "{topic}"'
                if query not in seen:
                    queries.append(query)
                    seen.add(query)
                if len(queries) >= limit:
                    return queries
    return queries[:limit]


def decode_duckduckgo_url(url: str) -> str:
    parsed = urlparse(url)
    if "duckduckgo.com" not in parsed.netloc:
        return url
    query = parse_qs(parsed.query)
    if "uddg" in query:
        return unquote(query["uddg"][0])
    return url


class ScrapyLeadPipeline:
    def open_spider(self, spider: scrapy.Spider) -> None:
        self.output_dir: Path = spider.output_dir
        self.log_file: Path = spider.log_file
        self.batch_size: int = spider.batch_size
        self.target_total: int = spider.target_total
        self.seen_contacts, self.seen_asins = spider.seen_contacts, spider.seen_asins
        self.total_rows = spider.total_rows
        self.batch_index = self.total_rows // self.batch_size + 1
        self.current_rows = self.load_batch_rows(self.output_dir / f"batch_{self.batch_index:03d}.csv")

    def process_item(self, item: dict[str, Any], spider: scrapy.Spider) -> dict[str, Any]:
        contact_key = (item.get("phone_or_email") or "").lower()
        asin = (item.get("asin") or "").upper()
        if not contact_key or not asin:
            raise DropItem("missing contact or asin")
        if contact_key in self.seen_contacts or asin in self.seen_asins:
            raise DropItem("duplicate")
        if self.total_rows >= self.target_total:
            raise DropItem("target reached")

        self.current_rows.append(item)
        self.seen_contacts.add(contact_key)
        self.seen_asins.add(asin)
        self.total_rows += 1
        spider.total_rows = self.total_rows

        batch_file = self.output_dir / f"batch_{self.batch_index:03d}.csv"
        write_rows(batch_file, self.current_rows)
        append_log(self.log_file, "row", self.batch_index, self.total_rows, f"{item['author_name']} -> {item['amazon_book_url']}")
        spider.logger.info("Added lead %s total=%s", item["author_name"], self.total_rows)

        if len(self.current_rows) >= self.batch_size:
            append_log(self.log_file, "batch_complete", self.batch_index, self.total_rows, str(batch_file))
            self.batch_index += 1
            self.current_rows = []
        return item

    def load_batch_rows(self, path: Path) -> list[dict[str, str]]:
        if not path.exists():
            return []
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))


class AuthorSiteSpider(scrapy.Spider):
    name = "author_site_spider"
    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "CONCURRENT_REQUESTS": 8,
        "DOWNLOAD_DELAY": 0.5,
        "RETRY_TIMES": 1,
        "LOG_LEVEL": "INFO",
        "USER_AGENT": "BookTrailerLeadFinder/1.0 (+public lead research; respects robots.txt)",
        "ITEM_PIPELINES": {
            "leadfinder.management.commands.scrape_scrapy_author_batches.ScrapyLeadPipeline": 300,
        },
    }

    def __init__(
        self,
        queries: list[str],
        seed_urls: list[str],
        seed_leads: dict[str, SeedLead],
        output_dir: Path,
        log_file: Path,
        batch_size: int,
        target_total: int,
        total_rows: int,
        seen_contacts: set[str],
        seen_asins: set[str],
        max_pages_per_site: int,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.queries = queries
        self.seed_urls = seed_urls
        self.seed_leads = seed_leads
        self.output_dir = output_dir
        self.log_file = log_file
        self.batch_size = batch_size
        self.target_total = target_total
        self.total_rows = total_rows
        self.seen_contacts = seen_contacts
        self.seen_asins = seen_asins
        self.max_pages_per_site = max_pages_per_site
        self.visited_sites: set[str] = set()
        self.pages_seen_by_site: dict[str, int] = {}

    async def start(self):
        for url in self.seed_urls:
            if blocked_url(url):
                continue
            site = root_url(url)
            self.visited_sites.add(site)
            yield scrapy.Request(
                url,
                callback=self.parse_author_page,
                meta={"query": "seed_url", "root": site, "depth": 0, "seed_lead": self.seed_leads.get(url)},
                errback=self.errback_log,
                dont_filter=True,
            )
        for query in self.queries:
            append_log(self.log_file, "query", self.total_rows // self.batch_size + 1, self.total_rows, query)
            encoded = quote_plus(query)
            yield scrapy.Request(
                f"https://html.duckduckgo.com/html/?q={encoded}",
                callback=self.parse_search,
                meta={"query": query, "engine": "duckduckgo"},
                dont_filter=True,
            )
            yield scrapy.Request(
                f"https://www.bing.com/search?q={encoded}&count=20",
                callback=self.parse_search,
                meta={"query": query, "engine": "bing"},
                dont_filter=True,
            )

    def parse_search(self, response: scrapy.http.Response):
        if self.total_rows >= self.target_total:
            return
        links = response.css("a.result__a::attr(href), li.b_algo h2 a::attr(href)").getall()
        for href in links:
            url = decode_duckduckgo_url(urljoin(response.url, href))
            if blocked_url(url):
                continue
            site = root_url(url)
            if site in self.visited_sites:
                continue
            self.visited_sites.add(site)
            yield scrapy.Request(
                url,
                callback=self.parse_author_page,
                meta={"query": response.meta["query"], "root": site, "depth": 0},
                errback=self.errback_log,
            )

    def parse_author_page(self, response: scrapy.http.Response):
        if self.total_rows >= self.target_total:
            return
        root = response.meta["root"]
        self.pages_seen_by_site[root] = self.pages_seen_by_site.get(root, 0) + 1

        text = " ".join(part.strip() for part in response.css("body ::text").getall() if part.strip())
        title = normalize_text(" ".join(response.css("title::text").getall()))
        heading = normalize_text(" ".join(response.css("h1::text, h2::text").getall()[:2]))
        author_name = author_from_page(title, heading, response.url)
        emails = [email for email in extract_emails(text) if valid_email(email)]
        phones = extract_phones(text, require_context=True)
        amazon_links = amazon_links_from_response(response)
        seed_lead: SeedLead | None = response.meta.get("seed_lead")

        if seed_lead and page_has_author_context(text):
            page_text = compact(f"{title} {heading} {text[:5000]} {response.url}")
            if compact(seed_lead.author_name) in page_text:
                seed_email_ok = bool(seed_lead.public_email and seed_lead.public_email.lower() in text.lower())
                seed_phone_ok = bool(seed_lead.public_phone and seed_lead.public_phone in text)
                if seed_email_ok or seed_phone_ok or emails or phones:
                    public_email = seed_lead.public_email or (emails[0] if emails else "")
                    public_phone = seed_lead.public_phone or (phones[0] if phones else "")
                    yield {
                        "author_name": seed_lead.author_name,
                        "phone_or_email": public_email or public_phone,
                        "public_email": public_email,
                        "public_phone": public_phone,
                        "amazon_book_url": seed_lead.amazon_book_url,
                        "book_title": seed_lead.book_title or title[:180],
                        "asin": seed_lead.asin,
                        "author_website": seed_lead.author_website or root,
                        "contact_page_url": response.url if "contact" in response.url.lower() else seed_lead.contact_page_url,
                        "contact_source_url": response.url,
                        "contact_source_title": title,
                        "contact_confidence": 0.86 if seed_email_ok or seed_phone_ok else 0.72,
                        "validation_status": "needs_manual_review",
                        "validation_notes": "Seed Amazon URL retained; Scrapy verified the public source page mentions the author and exposes contact data. Manual verification before outreach.",
                        "discovery_query": seed_lead.discovery_query,
                        "amazon_source_url": seed_lead.amazon_book_url,
                        "amazon_source_title": seed_lead.book_title,
                        "all_source_urls": response.url,
                    }

        if author_name and (emails or phones) and amazon_links and page_has_author_context(text):
            amazon_url = amazon_links[0]
            asin = extract_asin(amazon_url) or ""
            yield {
                "author_name": author_name,
                "phone_or_email": emails[0] if emails else phones[0],
                "public_email": emails[0] if emails else "",
                "public_phone": phones[0] if phones else "",
                "amazon_book_url": amazon_url,
                "book_title": title[:180],
                "asin": asin,
                "author_website": root,
                "contact_page_url": response.url if "contact" in response.url.lower() else "",
                "contact_source_url": response.url,
                "contact_source_title": title,
                "contact_confidence": 0.82 if "contact" in response.url.lower() else 0.74,
                "validation_status": "needs_manual_review",
                "validation_notes": "Contact and Amazon URL were scraped from a public children-author/illustrator site. Manual verification before outreach.",
                "discovery_query": response.meta["query"],
                "amazon_source_url": response.url,
                "amazon_source_title": title,
                "all_source_urls": response.url,
            }

        if response.meta["depth"] >= 1:
            return
        if self.pages_seen_by_site.get(root, 0) >= self.max_pages_per_site:
            return
        for href in response.css("a::attr(href)").getall():
            next_url = urljoin(response.url, href)
            if root_url(next_url) != root or blocked_url(next_url):
                continue
            lowered = next_url.lower()
            if not any(hint in lowered for hint in FOLLOW_HINTS):
                continue
            yield scrapy.Request(
                next_url,
                callback=self.parse_author_page,
                meta={"query": response.meta["query"], "root": root, "depth": response.meta["depth"] + 1},
                errback=self.errback_log,
            )

    def errback_log(self, failure):
        append_log(self.log_file, "request_error", self.total_rows // self.batch_size + 1, self.total_rows, str(failure.value)[:500])


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def append_log(path: Path, event: str, batch: int, total_rows: int, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_COLUMNS)
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp_utc": utc_now(),
                "event": event,
                "batch": batch,
                "total_rows": total_rows,
                "message": message[:2000],
            }
        )


class Command(BaseCommand):
    help = "Scrape public children-author sites with Scrapy and write separate 50-row CSV batches."

    def add_arguments(self, parser):
        parser.add_argument("--target-total", type=int, default=500)
        parser.add_argument("--batch-size", type=int, default=50)
        parser.add_argument("--output-dir", default="data/scrapy_validated_batches")
        parser.add_argument("--log-file", default="data/scrapy_validated_batches/scrapy_log.csv")
        parser.add_argument("--max-discovery-queries", type=int, default=120)
        parser.add_argument("--max-pages-per-site", type=int, default=5)
        parser.add_argument("--seed-url", action="append", default=[])
        parser.add_argument("--seed-csv", action="append", default=[])

    def handle(self, *args, **options):
        output_dir = Path(options["output_dir"])
        if not output_dir.is_absolute():
            output_dir = Path(settings.BASE_DIR) / output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        log_file = Path(options["log_file"])
        if not log_file.is_absolute():
            log_file = Path(settings.BASE_DIR) / log_file

        seen_contacts, seen_asins, total_rows = self.load_existing_state(output_dir)
        batch = total_rows // int(options["batch_size"]) + 1
        append_log(log_file, "start", batch, total_rows, "Starting Scrapy no-Tavily crawl")
        seed_urls = list(options["seed_url"] or [])
        seed_leads: dict[str, SeedLead] = {}
        for csv_path in options["seed_csv"] or []:
            urls, leads = self.seed_urls_from_csv(csv_path)
            seed_urls.extend(urls)
            seed_leads.update(leads)

        process = CrawlerProcess(
            settings={
                "LOG_LEVEL": "INFO",
            }
        )
        process.crawl(
            AuthorSiteSpider,
            queries=search_queries(max(0, int(options["max_discovery_queries"]))),
            seed_urls=seed_urls,
            seed_leads=seed_leads,
            output_dir=output_dir,
            log_file=log_file,
            batch_size=max(1, int(options["batch_size"])),
            target_total=max(1, int(options["target_total"])),
            total_rows=total_rows,
            seen_contacts=seen_contacts,
            seen_asins=seen_asins,
            max_pages_per_site=max(1, int(options["max_pages_per_site"])),
        )
        process.start()

        final_total = sum(1 for _ in self.iter_existing_rows(output_dir))
        append_log(log_file, "complete", final_total // int(options["batch_size"]) + 1, final_total, "Scrapy crawl completed")
        self.stdout.write(self.style.SUCCESS(f"Scrapy crawl completed. Total exported rows: {final_total}"))

    def seed_urls_from_csv(self, csv_path: str) -> tuple[list[str], dict[str, SeedLead]]:
        path = Path(csv_path)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        if not path.exists():
            return [], {}
        urls: list[str] = []
        leads: dict[str, SeedLead] = {}
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                author_name = row.get("author_name") or row.get("author") or ""
                amazon_book_url = row.get("amazon_book_url") or row.get("amazon_url") or ""
                public_email = row.get("public_email") or row.get("email") or ""
                public_phone = row.get("public_phone") or row.get("phone") or ""
                asin = row.get("asin") or extract_asin(amazon_book_url) or ""
                can_seed_lead = bool(author_name and amazon_book_url and (public_email or public_phone) and asin)
                for field in ["author_website", "contact_source_url", "contact_page_url"]:
                    url = row.get(field) or ""
                    if url.startswith(("http://", "https://")) and url not in urls:
                        urls.append(url)
                    if can_seed_lead and url.startswith(("http://", "https://")) and not blocked_url(url):
                        leads[url] = SeedLead(
                            author_name=author_name,
                            public_email=public_email,
                            public_phone=public_phone,
                            amazon_book_url=normalize_amazon_book_url(amazon_book_url),
                            book_title=row.get("book_title") or row.get("title") or "",
                            asin=asin.upper(),
                            author_website=row.get("author_website") or "",
                            contact_page_url=row.get("contact_page_url") or "",
                            discovery_query=f"seed_csv:{path.name}",
                        )
                for url in (row.get("all_source_urls") or "").split(";"):
                    url = url.strip()
                    if url.startswith(("http://", "https://")) and not blocked_url(url) and url not in urls:
                        urls.append(url)
        return urls, leads

    def load_existing_state(self, output_dir: Path) -> tuple[set[str], set[str], int]:
        contacts: set[str] = set()
        asins: set[str] = set()
        total = 0
        for row in self.iter_existing_rows(output_dir):
            total += 1
            if row.get("phone_or_email"):
                contacts.add(row["phone_or_email"].lower())
            if row.get("asin"):
                asins.add(row["asin"].upper())
        return contacts, asins, total

    def iter_existing_rows(self, output_dir: Path):
        for path in sorted(output_dir.glob("batch_*.csv")):
            with path.open(encoding="utf-8-sig", newline="") as handle:
                yield from csv.DictReader(handle)
