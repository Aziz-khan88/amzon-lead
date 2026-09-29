from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import QuerySet
from django.utils import timezone

from leadfinder.models import Lead, VerificationBatch
from leadfinder.services.social import harvest_social_profiles
from leadfinder.services.verification import verify_lead_contacts


class Command(BaseCommand):
    help = "Reinspect public social profiles and batch-verify all email/phone candidates."

    def add_arguments(self, parser):
        parser.add_argument("--lead-id", action="append", dest="lead_ids", default=[])
        parser.add_argument("--run-id")
        parser.add_argument("--status", choices=["verified", "not_verified", "other"])
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--no-social", action="store_true")
        parser.add_argument("--no-network", action="store_true")

    def _queryset(self, options) -> QuerySet:
        queryset = Lead.objects.select_related("book", "author_profile").prefetch_related("evidence")
        if options["lead_ids"]:
            queryset = queryset.filter(id__in=options["lead_ids"])
        if options.get("run_id"):
            queryset = queryset.filter(book__research_run_id=options["run_id"])
        if options.get("status"):
            queryset = queryset.filter(verification_status=options["status"])
        return queryset.order_by("created_at")

    def handle(self, *args, **options):
        queryset = self._queryset(options)
        if options["limit"] > 0:
            queryset = queryset[: options["limit"]]
        total = queryset.count() if hasattr(queryset, "count") else len(queryset)
        batch = VerificationBatch.objects.create(
            status="running",
            total_count=total,
            started_at=timezone.now(),
            settings_json={
                "inspect_social": not options["no_social"],
                "check_network": not options["no_network"],
                "run_id": options.get("run_id") or "",
            },
        )
        self.stdout.write(f"Verification batch {batch.id}: {total} leads")
        try:
            for lead in queryset.iterator(chunk_size=50):
                try:
                    if not options["no_social"]:
                        harvest_social_profiles(lead)
                    verify_lead_contacts(lead, batch=batch, check_network=not options["no_network"])
                    lead.refresh_from_db(fields=["verification_status", "verification_score"])
                    batch.processed_count += 1
                    if lead.verification_status == "verified":
                        batch.verified_count += 1
                    elif lead.verification_status == "not_verified":
                        batch.not_verified_count += 1
                    else:
                        batch.other_count += 1
                    self.stdout.write(
                        f"[{batch.processed_count}/{total}] {lead.book.author_name}: "
                        f"{lead.verification_status} ({lead.verification_score}/100)"
                    )
                except Exception as exc:
                    batch.processed_count += 1
                    batch.error_count += 1
                    self.stderr.write(f"Lead {lead.id}: {exc}")
                batch.save(
                    update_fields=[
                        "processed_count",
                        "verified_count",
                        "not_verified_count",
                        "other_count",
                        "error_count",
                        "updated_at",
                    ]
                )
            batch.status = "completed"
            batch.completed_at = timezone.now()
            batch.save(update_fields=["status", "completed_at", "updated_at"])
        except Exception as exc:
            batch.status = "failed"
            batch.error_message = str(exc)[:5000]
            batch.completed_at = timezone.now()
            batch.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
            raise
        self.stdout.write(
            self.style.SUCCESS(
                f"Complete: verified={batch.verified_count}, not_verified={batch.not_verified_count}, "
                f"other={batch.other_count}, errors={batch.error_count}"
            )
        )
