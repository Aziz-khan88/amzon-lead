from __future__ import annotations

from leadfinder.models import ResearchRun


class RunCanceled(Exception):
    """Raised when a background research run was canceled by the user."""


def raise_if_run_canceled(run_or_id) -> None:
    run_id = getattr(run_or_id, "id", run_or_id)
    if ResearchRun.objects.filter(id=run_id, status="canceled").exists():
        raise RunCanceled()
