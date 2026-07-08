from __future__ import annotations

import csv
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from leadfinder.management.commands.scrape_author_visit_leads import (
    OUTPUT_COLUMNS,
    Command as SingleScrapeCommand,
    blocked_url,
    build_discovery_queries,
    compact,
)


LOG_COLUMNS = ["timestamp_utc", "event", "batch", "total_rows", "message"]


class Command(BaseCommand):
    help = "Run children-author lead scraping in separate 50-row batch CSV files with a progress log."

    def add_arguments(self, parser):
        parser.add_argument("--target-total", type=int, default=500)
        parser.add_argument("--batch-size", type=int, default=50)
        parser.add_argument("--output-dir", default="data/validated_lead_batches")
        parser.add_argument("--log-file", default="data/validated_lead_batches/scrape_log.csv")
        parser.add_argument("--max-discovery-queries", type=int, default=500)
        parser.add_argument("--max-results", type=int, default=20)
        parser.add_argument("--max-pages-per-site", type=int, default=4)
        parser.add_argument("--no-fetch", action="store_true")
        parser.add_argument("--sleep", type=float, default=0.1)

    def handle(self, *args, **options):
        try:
            from tavily import TavilyClient
        except Exception as exc:
            raise RuntimeError("Install tavily-python before running this command.") from exc

        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            raise RuntimeError("TAVILY_API_KEY is required.")

        target_total = max(1, min(int(options["target_total"]), 1000))
        batch_size = max(1, min(int(options["batch_size"]), 100))
        max_results = max(1, min(int(options["max_results"]), 20))
        max_pages = max(1, min(int(options["max_pages_per_site"]), 8))
        sleep_seconds = max(0.0, float(options["sleep"]))

        output_dir = Path(options["output_dir"])
        if not output_dir.is_absolute():
            output_dir = Path(settings.BASE_DIR) / output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        log_file = Path(options["log_file"])
        if not log_file.is_absolute():
            log_file = Path(settings.BASE_DIR) / log_file
        log_file.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_log(log_file)

        client = TavilyClient(api_key)
        scraper = SingleScrapeCommand()
        queries = build_discovery_queries(max(1, int(options["max_discovery_queries"])))

        seen_authors, seen_contacts, seen_asins = self.load_existing_state(output_dir)
        total_rows = sum(1 for _ in self.iter_existing_rows(output_dir))
        current_batch_index = total_rows // batch_size + 1
        current_rows = self.load_batch_rows(output_dir / f"batch_{current_batch_index:03d}.csv")

        self.log(log_file, "start", current_batch_index, total_rows, f"Starting batch scrape target={target_total}")

        for query in queries:
            if total_rows >= target_total:
                break
            self.stdout.write(f"Finding author sites: {query}")
            self.log(log_file, "query", current_batch_index, total_rows, query)
            try:
                response = client.search(query=query, search_depth="advanced", max_results=max_results)
            except Exception as exc:
                message = str(exc)
                self.stderr.write(f"Discovery failed: {message}")
                self.log(log_file, "discovery_error", current_batch_index, total_rows, message)
                if self.is_limit_error(message):
                    break
                continue

            for item in response.get("results", []):
                if total_rows >= target_total:
                    break
                url = item.get("url") or ""
                if not url or blocked_url(url):
                    continue
                candidate = scraper.scrape_author_site(
                    url=url,
                    result_title=item.get("title") or "",
                    result_content=item.get("content") or "",
                    discovery_query=query,
                    max_pages=max_pages,
                    no_fetch=bool(options["no_fetch"]),
                )
                if not candidate:
                    continue
                author_key = compact(candidate.author_name)
                contact_key = (candidate.public_email or candidate.public_phone).lower()
                if author_key in seen_authors or contact_key in seen_contacts:
                    continue

                self.stdout.write(f"  Amazon match: {candidate.author_name}")
                try:
                    amazon = scraper.find_amazon_match(client, candidate)
                except Exception as exc:
                    message = str(exc)
                    self.log(log_file, "amazon_error", current_batch_index, total_rows, message)
                    if self.is_limit_error(message):
                        self.finish(log_file, current_batch_index, total_rows, "Stopped by Tavily limit/rate error.")
                        return
                    continue
                if not amazon or amazon.asin in seen_asins:
                    continue

                row = {
                    "author_name": candidate.author_name,
                    "phone_or_email": candidate.public_email or candidate.public_phone,
                    "public_email": candidate.public_email,
                    "public_phone": candidate.public_phone,
                    "amazon_book_url": amazon.amazon_book_url,
                    "book_title": amazon.book_title,
                    "asin": amazon.asin,
                    "author_website": candidate.author_website,
                    "contact_page_url": candidate.contact_page_url,
                    "contact_source_url": candidate.contact_source_url,
                    "contact_source_title": candidate.contact_source_title,
                    "contact_confidence": candidate.contact_confidence,
                    "validation_status": "needs_manual_review",
                    "validation_notes": "Contact is from a public author-owned children-book/author-visit page. Amazon URL is from public search-result metadata and matches the author. Manual verification before outreach.",
                    "discovery_query": candidate.discovery_query,
                    "amazon_source_url": amazon.amazon_source_url,
                    "amazon_source_title": amazon.amazon_source_title,
                    "all_source_urls": "; ".join(sorted(candidate.all_source_urls | {amazon.amazon_source_url})),
                }
                current_rows.append(row)
                total_rows += 1
                seen_authors.add(author_key)
                seen_contacts.add(contact_key)
                seen_asins.add(amazon.asin)

                batch_file = output_dir / f"batch_{current_batch_index:03d}.csv"
                self.write_rows(batch_file, current_rows)
                self.log(log_file, "row", current_batch_index, total_rows, f"{candidate.author_name} -> {amazon.amazon_book_url}")
                self.stdout.write(f"  + batch {current_batch_index:03d}: {len(current_rows)}/{batch_size}; total={total_rows}")

                if len(current_rows) >= batch_size:
                    self.log(log_file, "batch_complete", current_batch_index, total_rows, str(batch_file))
                    current_batch_index += 1
                    current_rows = []
            time.sleep(sleep_seconds)

        self.finish(log_file, current_batch_index, total_rows, "Completed available queries or target.")

    def load_existing_state(self, output_dir: Path) -> tuple[set[str], set[str], set[str]]:
        authors: set[str] = set()
        contacts: set[str] = set()
        asins: set[str] = set()
        for row in self.iter_existing_rows(output_dir):
            if row.get("author_name"):
                authors.add(compact(row["author_name"]))
            if row.get("phone_or_email"):
                contacts.add(row["phone_or_email"].lower())
            if row.get("asin"):
                asins.add(row["asin"].upper())
        return authors, contacts, asins

    def iter_existing_rows(self, output_dir: Path):
        for path in sorted(output_dir.glob("batch_*.csv")):
            with path.open(encoding="utf-8-sig", newline="") as handle:
                yield from csv.DictReader(handle)

    def load_batch_rows(self, path: Path) -> list[dict[str, str]]:
        if not path.exists():
            return []
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def write_rows(self, path: Path, rows: list[dict[str, object]]) -> None:
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    def ensure_log(self, path: Path) -> None:
        if path.exists():
            return
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            csv.DictWriter(handle, fieldnames=LOG_COLUMNS).writeheader()

    def log(self, path: Path, event: str, batch: int, total_rows: int, message: str) -> None:
        with path.open("a", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=LOG_COLUMNS)
            writer.writerow(
                {
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "event": event,
                    "batch": batch,
                    "total_rows": total_rows,
                    "message": message[:2000],
                }
            )

    def finish(self, log_file: Path, batch: int, total_rows: int, message: str) -> None:
        self.log(log_file, "complete", batch, total_rows, message)
        self.stdout.write(self.style.SUCCESS(f"{message} Total exported rows: {total_rows}"))

    def is_limit_error(self, message: str) -> bool:
        lowered = message.lower()
        return "usage limit" in lowered or "excessive requests" in lowered or "rate" in lowered
