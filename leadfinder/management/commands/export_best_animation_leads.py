from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q

from leadfinder.models import Lead
from leadfinder.services.export.csv_export import EXPORT_COLUMNS, lead_to_row
from leadfinder.utils.normalize import normalize_text

import csv


BAD_AUTHOR_TOKENS = [
    "amazon",
    "unknown",
    "this item",
    "paperback",
    "kindle",
    "audible",
    "step techniques",
    "ages",
]

GENERIC_CONTACT_DOMAINS = [
    "christianbook.com",
    "openlibrary.org",
    "archive.org",
    "teachingbooks.net",
    "audible.com",
    "cbsnews.com",
    "iloveprint.cn",
    "vitalsource.com",
    "amazon.com",
]


class Command(BaseCommand):
    help = "Export the best children's-book animation/video-service prospects."

    def add_arguments(self, parser):
        parser.add_argument("--output", default="data/best_animation_video_leads.csv")
        parser.add_argument("--limit", type=int, default=600)
        parser.add_argument("--require-email", action="store_true")
        parser.add_argument("--require-phone", action="store_true")

    def handle(self, *args, **options):
        output = Path(options["output"])
        if not output.is_absolute():
            output = Path(settings.BASE_DIR) / output
        output.parent.mkdir(parents=True, exist_ok=True)

        leads = (
            Lead.objects.select_related("book", "author_profile", "brief")
            .prefetch_related("evidence", "videos")
            .exclude(book__amazon_book_url="")
            .exclude(book__author_name="")
            .filter(do_not_contact=False)
            .filter(
                Q(public_email__gt="")
                | Q(public_phone__gt="")
                | Q(author_profile__canonical_website__gt="")
                | Q(author_profile__contact_page_url__gt="")
                | Q(author_profile__instagram_url__gt="")
                | Q(author_profile__facebook_url__gt="")
                | Q(author_profile__tiktok_url__gt="")
                | Q(author_profile__youtube_url__gt="")
                | Q(author_profile__linkedin_url__gt="")
            )
        )
        for token in BAD_AUTHOR_TOKENS:
            leads = leads.exclude(book__author_name__icontains=token)
        if options["require_email"]:
            leads = leads.exclude(public_email="")
        if options["require_phone"]:
            leads = leads.exclude(public_phone="")

        for domain in GENERIC_CONTACT_DOMAINS:
            leads = leads.exclude(public_email__icontains=domain).exclude(author_profile__canonical_website__icontains=domain)

        seen: set[str] = set()
        rows = []
        limit = max(1, min(options["limit"], 600))
        for lead in leads.order_by("-lead_score", "-extraction_confidence", "-created_at"):
            key = lead.book.asin or f"{normalize_text(lead.book.title)}::{normalize_text(lead.book.author_name)}"
            if key in seen:
                continue
            seen.add(key)
            rows.append(lead_to_row(lead))
            if len(rows) >= limit:
                break

        with output.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=EXPORT_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        count = len(rows)
        self.stdout.write(self.style.SUCCESS(f"Exported {count} best animation prospects to {output}"))
