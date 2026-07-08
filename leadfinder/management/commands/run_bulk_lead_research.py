from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from leadfinder.models import Lead, ResearchRun
from leadfinder.services.export.csv_export import export_leads_to_file
from leadfinder.services.pipeline.run_research import keyword_suggestions, run_research_pipeline


DEFAULT_KEYWORDS = [
    *keyword_suggestions(),
    "children book illustration",
    "children picture book",
    "kids picture book",
    "bedtime picture book",
    "illustrated children book",
    "independent children's author",
    "self published children's book",
    "children storybook",
    "kids bedtime story",
    "early reader picture book",
    "animal picture book",
    "rhyming children's book",
    "preschool picture book",
    "kindergarten picture book",
    "children book author",
    "picture book author",
    "children fantasy picture book",
    "social emotional learning picture book",
    "diverse children picture book",
    "holiday children picture book",
    "children author school visits contact phone",
    "picture book author booking email phone",
    "children author media kit contact",
    "children author speaking school visits",
    "children illustrator author contact phone",
]


class Command(BaseCommand):
    help = "Run repeated research batches until a target lead count is reached, then export CSV."

    def add_arguments(self, parser):
        parser.add_argument("--keyword", action="append", dest="keywords")
        parser.add_argument("--target-leads", type=int, default=700)
        parser.add_argument("--batch-size", type=int, default=25)
        parser.add_argument("--provider", default="tavily", choices=["ddgs", "tavily", "brave", "google", "google_books"])
        parser.add_argument("--output", default="data/book_trailer_leads_700.csv")
        parser.add_argument("--no-video-search", action="store_true")
        parser.add_argument("--no-ai", action="store_true")
        parser.add_argument("--require-public-email", action="store_true")
        parser.add_argument("--max-batches", type=int, default=40)
        parser.add_argument("--include-existing", action="store_true")
        parser.add_argument("--allow-missing-amazon-url", action="store_true")
        parser.add_argument("--allow-missing-author", action="store_true")
        parser.add_argument("--allow-missing-email", action="store_true")
        parser.add_argument("--allow-missing-phone", action="store_true")

    def _output_path(self, output_option: str) -> Path:
        output = Path(output_option)
        if not output.is_absolute():
            output = Path(settings.BASE_DIR) / output
        output.parent.mkdir(parents=True, exist_ok=True)
        return output

    def _qualified_queryset(self, options, run_ids: list[str] | None = None):
        qs = Lead.objects.order_by("-lead_score", "-created_at")
        if run_ids is not None:
            qs = qs.filter(book__research_run_id__in=run_ids)
        if not options["allow_missing_amazon_url"]:
            qs = qs.exclude(book__amazon_book_url="")
        if not options["allow_missing_author"]:
            qs = qs.exclude(book__author_name="")
        if not options["allow_missing_email"]:
            qs = qs.exclude(public_email="")
        if not options["allow_missing_phone"]:
            qs = qs.exclude(public_phone="")
        return qs.filter(do_not_contact=False)

    def handle(self, *args, **options):
        target = max(1, min(options["target_leads"], 700))
        batch_size = max(1, min(options["batch_size"], 100))
        keywords = options["keywords"] or DEFAULT_KEYWORDS
        created_run_ids: list[str] = []

        self.stdout.write(
            f"Starting bulk lead research: target={target}, provider={options['provider']}, batch_size={batch_size}"
        )
        try:
            for index in range(options["max_batches"]):
                current_total = self._qualified_queryset(
                    options,
                    None if options["include_existing"] else created_run_ids,
                ).count()
                if current_total >= target:
                    break
                keyword = keywords[index % len(keywords)]
                run = ResearchRun.objects.create(
                    keyword=keyword,
                    source_provider=options["provider"],
                    max_books=batch_size,
                    settings_json={
                        "require_public_email": options["require_public_email"],
                        "run_video_search": not options["no_video_search"],
                        "run_groq_ai_extraction": not options["no_ai"],
                        "bulk_target_leads": target,
                    },
                )
                created_run_ids.append(str(run.id))
                self.stdout.write(f"[{index + 1}] Running {keyword!r} as {run.id}")
                try:
                    run_research_pipeline(run.id)
                except KeyboardInterrupt:
                    run.mark_canceled()
                    self.stdout.write(self.style.WARNING(f"Run {run.id} interrupted by user. Marked as canceled in database."))
                    raise
                except Exception as exc:
                    self.stderr.write(f"Run {run.id} failed: {exc}")

                run.refresh_from_db()
                if run.status == "canceled":
                    self.stdout.write(self.style.WARNING(f"Run {run.id} was canceled/stopped. Stopping bulk execution loop."))
                    break

                progress_queryset = self._qualified_queryset(
                    options,
                    None if options["include_existing"] else created_run_ids,
                )
                progress_count = progress_queryset.count()
                output = self._output_path(options["output"])
                exported = export_leads_to_file(progress_queryset[:target], str(output))
                self.stdout.write(
                    f"Progress: {progress_count}/{target} qualified required-field leads; exported {exported} rows to {output}"
                )
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nBulk lead research interrupted by user (Ctrl+C). Cleaning up and exporting..."))

        final_queryset = self._qualified_queryset(
            options,
            None if options["include_existing"] else created_run_ids,
        )
        final_count = final_queryset.count()
        export_limit = min(final_count, target)
        output = self._output_path(options["output"])
        exported = export_leads_to_file(final_queryset[:export_limit], str(output))
        self.stdout.write(
            self.style.SUCCESS(
                f"Bulk research complete. Created/selected {final_count} leads; exported {exported} rows to {output}."
            )
        )
