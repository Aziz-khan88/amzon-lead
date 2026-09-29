import logging
import sys

from django.apps import AppConfig
from django.db.backends.signals import connection_created


logger = logging.getLogger(__name__)


def _sqlite_performance_pragmas(sender, connection, **kwargs):
    """Enable WAL + busy timeout so pipeline threads and web requests share the DB."""
    if connection.vendor != "sqlite":
        return
    try:
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA busy_timeout=30000;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
    except Exception:
        # In-memory test databases do not support WAL; never break startup.
        logger.debug("SQLite performance pragmas skipped", exc_info=True)


class LeadfinderConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "leadfinder"
    verbose_name = "Book Trailer Lead Finder"

    def ready(self):
        from . import signals  # noqa: F401

        connection_created.connect(_sqlite_performance_pragmas)
        self._recover_interrupted_runs()

    def _recover_interrupted_runs(self):
        """Mark runs orphaned by a server restart as failed.

        Background pipelines run as daemon threads inside the web process, so
        any run still "pending"/"running" at server boot lost its worker and
        would otherwise spin forever in the UI.  Only runs in the actual web
        server process (never during tests, migrations, or shell commands).
        """
        server_commands = {"runserver", "runserver_plus", "daphne", "gunicorn", "uvicorn"}
        if not any(command in sys.argv for command in server_commands):
            return
        try:
            from .models import ResearchRun, ScheduledLeadTask

            stuck_runs = ResearchRun.objects.filter(status__in=["pending", "running"]).update(
                status="failed",
                error_message="Server restarted while this run was in progress. Start a retry to run it again.",
            )
            stuck_tasks = ScheduledLeadTask.objects.filter(execution_status="running").update(
                execution_status="failed",
                last_error="Server restarted while this task was running.",
            )
            if stuck_runs or stuck_tasks:
                logger.warning(
                    "Recovered interrupted work after restart: %s run(s), %s scheduled task(s) marked failed.",
                    stuck_runs,
                    stuck_tasks,
                )
        except Exception:
            # The database may not be migrated yet during first boot.
            logger.exception("Interrupted-run recovery sweep failed")
