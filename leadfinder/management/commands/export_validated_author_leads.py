from __future__ import annotations

import csv
import re
from pathlib import Path
from urllib.parse import urlparse

import tldextract
from django.conf import settings
from django.core.management.base import BaseCommand
from email_validator import EmailNotValidError, validate_email

from leadfinder.models import Lead
from leadfinder.utils.normalize import normalize_text


DOMAIN_EXTRACTOR = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


BAD_AUTHOR_TOKENS = [
    "amazon",
    "unknown",
    "this item",
    "paperback",
    "kindle",
    "audible",
    "academy award",
    "best seller",
    "children's books",
    "book series",
]

GENERIC_CONTACT_DOMAINS = {
    "amazon.com",
    "audible.com",
    "archive.org",
    "barnesandnoble.com",
    "booksamillion.com",
    "christianbook.com",
    "goodreads.com",
    "ibt.com",
    "openlibrary.org",
    "teachingbooks.net",
    "worldcat.org",
    "youtube.com",
    "youtu.be",
}

EXPORT_COLUMNS = [
    "author_name",
    "public_email",
    "public_phone",
    "amazon_book_url",
    "book_title",
    "asin",
    "author_website",
    "contact_page_url",
    "contact_source_url",
    "contact_confidence",
    "verification_score",
    "verification_status",
    "verification_reason",
    "suggested_first_line",
    "all_source_urls",
]


def registered_domain(url: str) -> str:
    host = urlparse(url or "").hostname or ""
    if not host:
        return ""
    extracted = DOMAIN_EXTRACTOR(host)
    if not extracted.domain or not extracted.suffix:
        return host.lower()
    return f"{extracted.domain}.{extracted.suffix}".lower()


def is_valid_author_name(name: str) -> bool:
    normalized = normalize_text(name)
    if not normalized or len(normalized) < 5 or len(normalized) > 90:
        return False
    lowered = normalized.lower()
    if any(token in lowered for token in BAD_AUTHOR_TOKENS):
        return False
    if any(char in normalized for char in [":", "/", "\\", "..."]):
        return False
    tokens = re.findall(r"[A-Za-z][A-Za-z'.-]+", normalized)
    return len(tokens) >= 2


def compact_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def author_identity_appears_in_url_or_text(author_name: str, *values: str) -> bool:
    tokens = [token for token in re.findall(r"[A-Za-z][A-Za-z'.-]+", author_name.lower()) if len(token) >= 4]
    if not tokens:
        return False
    compact_author = compact_text(author_name)
    text = " ".join(values).lower()
    compact = compact_text(text)
    if compact_author and compact_author in compact:
        return True
    return sum(1 for token in tokens if token in text or token in compact) >= min(2, len(tokens))


def is_valid_email(email: str) -> bool:
    if not email:
        return False
    try:
        validate_email(email, check_deliverability=False)
    except EmailNotValidError:
        return False
    return True


def best_contact_evidence(lead):
    evidence = list(
        lead.evidence.filter(field_name__in=["public_email", "public_phone"])
        .exclude(source_url="")
        .order_by("-confidence", "-created_at")
    )
    if not evidence:
        return None

    author = lead.author_profile
    author_identity_sources = [
        author.canonical_website if author else "",
        author.contact_page_url if author else "",
        author.identity_reason if author else "",
    ]
    if not author_identity_appears_in_url_or_text(lead.book.author_name, *author_identity_sources):
        return None

    author_domains = {
        registered_domain(url)
        for url in [
            author.canonical_website if author else "",
            author.contact_page_url if author else "",
            author.publisher_url if author else "",
        ]
        if url
    }
    author_domains.discard("")

    for item in evidence:
        source_domain = registered_domain(item.source_url)
        if source_domain in GENERIC_CONTACT_DOMAINS:
            continue
        source_mentions_identity = author_identity_appears_in_url_or_text(
            lead.book.author_name,
            item.source_url,
            item.source_title,
            item.source_snippet,
        )
        if item.confidence >= 0.65 and source_domain in author_domains and source_mentions_identity:
            return item
        if (
            item.evidence_type in {"contact_page", "official_author_site", "groq_extraction"}
            and item.confidence >= 0.6
            and source_mentions_identity
        ):
            return item
    return None


def validation_errors(lead, contact_evidence) -> list[str]:
    errors: list[str] = []
    book = lead.book
    if not is_valid_author_name(book.author_name):
        errors.append("author_name is not a usable personal/pen name")
    if not book.amazon_book_url or "/dp/" not in book.amazon_book_url:
        errors.append("amazon_book_url is missing or not normalized")
    if not lead.public_email and not lead.public_phone:
        errors.append("missing public email or phone")
    if lead.public_email and not is_valid_email(lead.public_email):
        errors.append("public_email failed syntax validation")
    if not contact_evidence:
        errors.append("contact source did not pass relevance/confidence checks")
    if lead.do_not_contact or lead.manual_review_status == "do_not_contact":
        errors.append("lead is marked do-not-contact")
    if lead.verification_status != "verified":
        errors.append("contact has not passed every verification hard gate")
    return errors


def lead_key(lead) -> str:
    if lead.book.asin:
        return lead.book.asin.upper()
    if lead.public_email:
        return lead.public_email.lower()
    return f"{normalize_text(lead.book.author_name)}::{normalize_text(lead.book.title)}"


class Command(BaseCommand):
    help = "Export strict, source-linked children's book author leads for outreach review."

    def add_arguments(self, parser):
        parser.add_argument("--output", default="data/validated_children_book_author_leads.csv")
        parser.add_argument("--limit", type=int, default=700)

    def handle(self, *args, **options):
        output = Path(options["output"])
        if not output.is_absolute():
            output = Path(settings.BASE_DIR) / output
        output.parent.mkdir(parents=True, exist_ok=True)

        queryset = (
            Lead.objects.select_related("book", "author_profile", "primary_contact")
            .prefetch_related("evidence")
            .exclude(book__amazon_book_url="")
            .exclude(book__author_name="")
            .filter(do_not_contact=False)
            .filter(verification_status="verified")
            .order_by("-verification_score", "-created_at")
        )

        rows: list[dict[str, object]] = []
        seen: set[str] = set()
        skipped = 0
        limit = max(1, min(int(options["limit"]), 700))
        for lead in queryset:
            contact_evidence = best_contact_evidence(lead)
            errors = validation_errors(lead, contact_evidence)
            if errors:
                skipped += 1
                continue
            key = lead_key(lead)
            if key in seen:
                continue
            seen.add(key)
            author = lead.author_profile
            all_urls = list(lead.evidence.exclude(source_url="").values_list("source_url", flat=True).distinct())
            rows.append(
                {
                    "author_name": lead.book.author_name,
                    "public_email": lead.public_email,
                    "public_phone": lead.public_phone,
                    "amazon_book_url": lead.book.amazon_book_url,
                    "book_title": lead.book.title,
                    "asin": lead.book.asin,
                    "author_website": author.canonical_website if author else "",
                    "contact_page_url": author.contact_page_url if author else "",
                    "contact_source_url": contact_evidence.source_url if contact_evidence else "",
                    "contact_confidence": contact_evidence.confidence if contact_evidence else "",
                    "verification_score": lead.verification_score,
                    "verification_status": lead.verification_status,
                    "verification_reason": lead.verification_reason,
                    "suggested_first_line": lead.suggested_first_line,
                    "all_source_urls": "; ".join(all_urls),
                }
            )
            if len(rows) >= limit:
                break

        with output.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=EXPORT_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

        self.stdout.write(
            self.style.SUCCESS(
                f"Exported {len(rows)} verified leads to {output}. Skipped {skipped} candidates."
            )
        )
