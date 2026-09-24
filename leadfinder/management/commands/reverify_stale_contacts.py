"""Re-verify leads whose contact evidence has gone stale.

Public contact data decays (authors change emails, domains lapse).  Leads
whose newest contact check is older than ``APP_CONTACT_STALE_DAYS``
(default 90) are flagged ``contacts_stale`` and re-run through
``verify_lead_contacts``; leads that fail re-verification drop back to
``other``/``not_verified`` instead of silently shipping outdated data.

Usage:
    python manage.py reverify_stale_contacts [--days 90] [--limit 200] [--no-network]
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Max, Q
from django.utils import timezone

from leadfinder.models import ContactCandidate, Lead
from leadfinder.services.verification import verify_lead_contacts


class Command(BaseCommand):
    help = "Flag and re-verify leads with stale contact verification."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=int(getattr(settings, "APP_CONTACT_STALE_DAYS", 90)))
        parser.add_argument("--limit", type=int, default=200)
        parser.add_argument("--no-network", action="store_true", help="Skip SMTP/API deliverability checks")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        limit = max(1, options["limit"])
        check_network = not options["no_network"]

        stale_lead_ids = (
            ContactCandidate.objects.filter(lead__verification_status="verified")
            .values("lead_id")
            .annotate(last_check=Max("last_checked_at"))
            .filter(Q(last_check__lt=cutoff) | Q(last_check__isnull=True))
            .values_list("lead_id", flat=True)[:limit]
        )
        leads = list(Lead.objects.filter(id__in=list(stale_lead_ids)).select_related("book", "author_profile"))
        if not leads:
            self.stdout.write(self.style.SUCCESS("No stale verified leads found."))
            return

        now = timezone.now()
        Lead.objects.filter(id__in=[lead.id for lead in leads]).update(
            contacts_stale=True, contacts_flagged_stale_at=now, updated_at=now
        )
        self.stdout.write(f"Flagged {len(leads)} leads as stale (>{options['days']} days since last check). Re-verifying...")

        re_verified = 0
        downgraded = 0
        for lead in leads:
            try:
                verify_lead_contacts(lead, check_network=check_network)
                lead.refresh_from_db(fields=["verification_status"])
                if lead.verification_status == "verified":
                    re_verified += 1
                    Lead.objects.filter(id=lead.id).update(contacts_stale=False, updated_at=timezone.now())
                else:
                    downgraded += 1
                    warnings = list(lead.warnings_json or [])
                    warnings.append(
                        f"Contacts re-checked after {options['days']} days and no longer verify; treat as stale."
                    )
                    Lead.objects.filter(id=lead.id).update(warnings_json=warnings, updated_at=timezone.now())
            except Exception as exc:  # noqa: BLE001 - one bad lead must not stop the batch
                self.stderr.write(f"Re-verification failed for lead {lead.id}: {exc}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {len(leads)} stale leads processed, {re_verified} re-verified, {downgraded} downgraded."
            )
        )
