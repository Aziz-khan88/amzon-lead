from __future__ import annotations

from django.core.management.base import BaseCommand

from leadfinder.models import Lead
from leadfinder.services.pipeline.quality_gate import has_verified_contact_source
from leadfinder.services.pipeline.source_audit import is_catalog_or_platform_source
from leadfinder.services.scoring.lead_score import score_from_lead


class Command(BaseCommand):
    help = "Clear stale contacts sourced from catalogs, libraries, bookstores, or otherwise untrusted pages."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=0, help="Maximum leads to scan; 0 scans all leads.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        limit = max(0, int(options["limit"] or 0))
        queryset = (
            Lead.objects.select_related("book", "author_profile")
            .prefetch_related("evidence")
            .order_by("-updated_at")
        )
        if limit:
            queryset = queryset[:limit]

        scanned = 0
        changed = 0
        cleared_contacts = 0
        cleared_urls = 0

        for lead in queryset:
            scanned += 1
            lead_fields: list[str] = []
            profile_fields: list[str] = []
            warnings = list(lead.warnings_json or [])
            author = lead.author_profile

            for field in ["public_email", "public_phone", "representation_email", "publicist_email"]:
                value = getattr(lead, field)
                if not value:
                    continue
                min_confidence = 0.55 if field == "public_phone" else 0.6
                if has_verified_contact_source(lead, field, value, min_confidence=min_confidence):
                    continue
                setattr(lead, field, "")
                lead_fields.append(field)
                cleared_contacts += 1
                warnings.append(f"Sanitized {field}: source did not pass trusted author/agent/publisher checks.")
                if author and field in {"representation_email", "publicist_email"} and getattr(author, field):
                    setattr(author, field, "")
                    profile_fields.append(field)

            if author:
                for field in ["canonical_website", "contact_page_url", "publisher_url"]:
                    value = getattr(author, field)
                    if not value or not is_catalog_or_platform_source(value):
                        continue
                    setattr(author, field, "")
                    profile_fields.append(field)
                    cleared_urls += 1
                    warnings.append(f"Sanitized {field}: removed catalog/bookstore/library URL {value}.")

            if not lead_fields and not profile_fields:
                continue

            lead.warnings_json = warnings
            lead.lead_score, lead.lead_tier = score_from_lead(lead)
            if lead.lead_tier == "rejected":
                lead.manual_review_status = "rejected"
            lead_fields.extend(["warnings_json", "lead_score", "lead_tier", "service_needs_json", "manual_review_status", "updated_at"])

            changed += 1
            if not dry_run:
                lead.save(update_fields=list(dict.fromkeys(lead_fields)))
                if author and profile_fields:
                    author.save(update_fields=list(dict.fromkeys([*profile_fields, "updated_at"])))

        mode = "Would update" if dry_run else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode} {changed} of {scanned} scanned leads. "
                f"Cleared {cleared_contacts} contact values and {cleared_urls} catalog URLs."
            )
        )

