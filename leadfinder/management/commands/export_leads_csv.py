from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from leadfinder.models import Lead
from leadfinder.services.export.csv_export import export_leads_to_file


class Command(BaseCommand):
    help = "Export leads to a CSV file."

    def add_arguments(self, parser):
        parser.add_argument("--output", default="data/book_trailer_leads_700.csv")
        parser.add_argument("--limit", type=int, default=700)
        parser.add_argument("--status", choices=["verified", "not_verified", "other"])
        parser.add_argument("--with-email", action="store_true")
        parser.add_argument("--required-fields", action="store_true")
        parser.add_argument("--amazon-author-required", action="store_true")
        parser.add_argument("--with-social", action="store_true")
        parser.add_argument("--include-do-not-contact", action="store_true")

    def handle(self, *args, **options):
        output = Path(options["output"])
        if not output.is_absolute():
            output = Path(settings.BASE_DIR) / output
        output.parent.mkdir(parents=True, exist_ok=True)

        leads = Lead.objects.select_related("book", "author_profile", "primary_contact").order_by("-verification_score", "-created_at")
        if options["status"]:
            leads = leads.filter(verification_status=options["status"])
        if options["with_email"]:
            leads = leads.exclude(public_email="")
        if options["amazon_author_required"]:
            leads = leads.exclude(book__amazon_book_url="").exclude(book__author_name="")
        if options["required_fields"]:
            leads = leads.exclude(book__amazon_book_url="").exclude(book__author_name="").exclude(public_email="").exclude(public_phone="")
        if options["with_social"]:
            leads = leads.filter(
                author_profile__instagram_url__gt=""
            ) | leads.filter(
                author_profile__facebook_url__gt=""
            ) | leads.filter(
                author_profile__tiktok_url__gt=""
            ) | leads.filter(
                author_profile__youtube_url__gt=""
            ) | leads.filter(
                author_profile__linkedin_url__gt=""
            )
        if not options["include_do_not_contact"]:
            leads = leads.filter(do_not_contact=False)
        leads = leads[: max(1, min(options["limit"], 700))]

        count = export_leads_to_file(leads, str(output))
        self.stdout.write(self.style.SUCCESS(f"Exported {count} leads to {output}"))
