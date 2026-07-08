from __future__ import annotations

from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Seed the app with synthetic demo children's book data."

    def handle(self, *args, **options):
        path = Path(settings.BASE_DIR) / "data" / "demo_books.csv"
        call_command("import_books_csv", str(path), no_video_search=True, no_ai=True)
        self.stdout.write(self.style.SUCCESS("Demo data seeded."))
