from __future__ import annotations

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from leadfinder.models import ResearchRun
from leadfinder.services.pipeline.run_research import run_research_pipeline
from leadfinder.views import import_books_from_rows


class Command(BaseCommand):
    help = "Import book leads from CSV and run enrichment."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--no-video-search", action="store_true")
        parser.add_argument("--no-ai", action="store_true")
        parser.add_argument(
            "--enrichment-provider",
            choices=["ddgs", "tavily", "brave", "google"],
            help="Search provider to use for author/contact enrichment during CSV imports.",
        )

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"CSV not found: {path}")
        with path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        settings_json = {
            "run_video_search": not options["no_video_search"],
            "run_groq_ai_extraction": not options["no_ai"],
        }
        if options.get("enrichment_provider"):
            settings_json["enrichment_provider"] = options["enrichment_provider"]

        run = ResearchRun.objects.create(
            keyword=f"CSV import: {path.name}",
            source_provider="csv",
            max_books=max(len(rows), 1),
            settings_json=settings_json,
        )
        imported = import_books_from_rows(rows, run, source_label=str(path))
        run.max_books = imported
        run.save(update_fields=["max_books"])
        run_research_pipeline(run.id)
        self.stdout.write(self.style.SUCCESS(f"Imported {imported} books in run {run.id}"))
