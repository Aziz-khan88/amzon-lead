from __future__ import annotations

from django.core.management.base import BaseCommand

from leadfinder.models import ResearchRun
from leadfinder.services.pipeline.run_research import run_research_pipeline


class Command(BaseCommand):
    help = "Run keyword-based lead research using a configured search provider."

    def add_arguments(self, parser):
        parser.add_argument("--keyword", required=True)
        parser.add_argument("--max-books", type=int, default=25)
        parser.add_argument("--provider", default="ddgs", choices=["ddgs", "tavily", "brave", "amazon_creators", "google_books"])
        parser.add_argument("--require-public-email", action="store_true")
        parser.add_argument("--no-video-search", action="store_true")
        parser.add_argument("--no-ai", action="store_true")

    def handle(self, *args, **options):
        run = ResearchRun.objects.create(
            keyword=options["keyword"],
            source_provider=options["provider"],
            max_books=options["max_books"],
            settings_json={
                "require_public_email": options["require_public_email"],
                "run_video_search": not options["no_video_search"],
                "run_groq_ai_extraction": not options["no_ai"],
            },
        )
        run_research_pipeline(run.id)
        self.stdout.write(self.style.SUCCESS(f"Research run completed: {run.id}"))
