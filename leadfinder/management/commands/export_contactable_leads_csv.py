from __future__ import annotations

import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from leadfinder.management.commands.export_validated_author_leads import (
    author_identity_appears_in_url_or_text,
    is_valid_author_name,
    is_valid_email,
    lead_key,
    registered_domain,
)
from leadfinder.models import Lead


BAD_AUTHOR_HINTS = {
    "amazon",
    "books",
    "children",
    "illustrated",
    "publishing",
    "publisher",
    "calendar",
    "library",
    "school",
    "story",
    "university",
    "press",
    "bookshop",
    "bookstore",
    "at-a-glance",
}

GENERIC_CONTACT_DOMAINS = {
    "amazon.com",
    "archive.org",
    "audible.com",
    "barnesandnoble.com",
    "booktopia.com.au",
    "booksamillion.com",
    "goodreads.com",
    "kdp.amazon.com",
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "linkedin.com",
    "mitpressbookstore.mit.edu",
    "openlibrary.org",
    "worldcat.org",
}

EXPORT_COLUMNS = [
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
    "contact_confidence",
    "lead_score",
    "lead_tier",
    "validation_status",
    "validation_notes",
    "suggested_first_line",
    "all_source_urls",
]


def author_name_is_outreach_usable(name: str) -> bool:
    lowered = (name or "").lower()
    if any(hint in lowered for hint in BAD_AUTHOR_HINTS):
        return False
    return is_valid_author_name(name)


def matching_contact_evidence(lead, field_name: str):
    evidence = (
        lead.evidence.filter(field_name=field_name)
        .exclude(source_url="")
        .order_by("-confidence", "-created_at")
    )
    for item in evidence:
        if item.confidence < 0.45:
            continue
        if field_name == "public_email" and not is_valid_email(item.field_value):
            continue
        if registered_domain(item.source_url) in GENERIC_CONTACT_DOMAINS:
            continue
        if not author_identity_appears_in_url_or_text(
            lead.book.author_name,
            item.source_url,
            item.source_title,
            item.source_snippet,
        ):
            continue
        return item
    return None


class Command(BaseCommand):
    help = "Export contactable author leads with required author, contact, and Amazon book URL fields."

    def add_arguments(self, parser):
        parser.add_argument("--output", default="data/contactable_children_book_author_leads.csv")
        parser.add_argument("--limit", type=int, default=700)

    def handle(self, *args, **options):
        output = Path(options["output"])
        if not output.is_absolute():
            output = Path(settings.BASE_DIR) / output
        output.parent.mkdir(parents=True, exist_ok=True)
        limit = max(1, min(int(options["limit"]), 700))

        queryset = (
            Lead.objects.select_related("book", "author_profile")
            .prefetch_related("evidence")
            .exclude(book__amazon_book_url="")
            .exclude(book__author_name="")
            .filter(do_not_contact=False)
            .order_by("-lead_score", "-extraction_confidence", "-created_at")
        )

        rows: list[dict[str, object]] = []
        seen: set[str] = set()
        rejected = 0
        for lead in queryset:
            if not author_name_is_outreach_usable(lead.book.author_name):
                rejected += 1
                continue
            email_evidence = matching_contact_evidence(lead, "public_email")
            phone_evidence = matching_contact_evidence(lead, "public_phone")
            if not email_evidence and not phone_evidence:
                rejected += 1
                continue
            contact_evidence = email_evidence or phone_evidence
            public_email = email_evidence.field_value if email_evidence else ""
            public_phone = phone_evidence.field_value if phone_evidence else ""
            key = lead_key(lead)
            if key in seen:
                continue
            seen.add(key)
            author = lead.author_profile
            all_urls = list(lead.evidence.exclude(source_url="").values_list("source_url", flat=True).distinct())
            rows.append(
                {
                    "author_name": lead.book.author_name,
                    "phone_or_email": public_email or public_phone,
                    "public_email": public_email,
                    "public_phone": public_phone,
                    "amazon_book_url": lead.book.amazon_book_url,
                    "book_title": lead.book.title,
                    "asin": lead.book.asin,
                    "author_website": author.canonical_website if author else "",
                    "contact_page_url": author.contact_page_url if author else "",
                    "contact_source_url": contact_evidence.source_url,
                    "contact_confidence": contact_evidence.confidence,
                    "lead_score": lead.lead_score,
                    "lead_tier": lead.lead_tier,
                    "validation_status": "needs_manual_review",
                    "validation_notes": "Required fields present; contact source mentions the author and passed basic syntax/domain checks.",
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

        self.stdout.write(self.style.SUCCESS(f"Exported {len(rows)} leads to {output}. Rejected {rejected} weak rows."))
