from __future__ import annotations

from django.core.management.base import BaseCommand

from leadfinder.models import ResearchRun
from leadfinder.services.pipeline.run_research import run_research_pipeline


class Command(BaseCommand):
    help = "Run BookLife category discovery and author lead enrichment."

    def add_arguments(self, parser):
        parser.add_argument(
            "--category",
            action="append",
            dest="categories",
            default=[],
            help="BookLife category slug. Repeat for multiple categories. Defaults to all categories.",
        )
        parser.add_argument(
            "--age-filter",
            default="all",
            choices=["all", "adult", "children-young-adult"],
        )
        parser.add_argument("--max-books", type=int, default=25)
        parser.add_argument(
            "--enrichment-provider",
            default="ddgs",
            choices=["ddgs", "tavily", "brave", "google"],
        )
        parser.add_argument("--require-public-email", action="store_true")
        parser.add_argument("--no-video-search", action="store_true")
        parser.add_argument("--no-ai", action="store_true")

    def handle(self, *args, **options):
        categories = options["categories"] or ["all"]
        run = ResearchRun.objects.create(
            keyword=f"BookLife: {', '.join(categories)}",
            source_provider="booklife",
            max_books=options["max_books"],
            settings_json={
                "booklife_categories": categories,
                "booklife_category_labels": categories,
                "booklife_age_filter": options["age_filter"],
                "enrichment_provider": options["enrichment_provider"],
                "require_amazon_url": False,
                "require_public_email": options["require_public_email"],
                "include_social_only_leads": True,
                "run_video_search": not options["no_video_search"],
                "run_groq_ai_extraction": not options["no_ai"],
            },
        )
        run_research_pipeline(run.id)
        self.stdout.write(self.style.SUCCESS(f"BookLife research run completed: {run.id}"))
