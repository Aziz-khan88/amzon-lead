from django.apps import AppConfig


class LeadfinderConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "leadfinder"
    verbose_name = "Book Trailer Lead Finder"

    def ready(self):
        from . import signals  # noqa: F401
