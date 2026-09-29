from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import F, Q
from django.utils import timezone

from leadfinder.models import ContactCandidate, ResearchRun, ScheduledLeadTask
from leadfinder.services.pipeline.run_research import run_research_pipeline


WEEKDAY_INDEX = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


def calculate_next_run_at(
    task: ScheduledLeadTask,
    *,
    from_time: datetime | None = None,
) -> datetime:
    """Return the next timezone-aware occurrence strictly after a completed interval.

    Calendar schedules may still use today's configured time when it is in the
    future. Interval schedules always start from ``from_time``.
    """

    reference = from_time or timezone.now()
    local_reference = timezone.localtime(reference)
    current_tz = timezone.get_current_timezone()

    if task.frequency == "interval_hours":
        hours = min(max(int(task.interval_hours or 1), 1), 720)
        return reference + timedelta(hours=hours)

    def occurrence(day_offset: int) -> datetime:
        local_date = local_reference.date() + timedelta(days=day_offset)
        naive = datetime.combine(local_date, task.run_time)
        return timezone.make_aware(naive, current_tz)

    if task.frequency == "daily":
        today = occurrence(0)
        return today if today > reference else occurrence(1)

    configured_days = [
        WEEKDAY_INDEX[value]
        for value in (task.days_of_week or [])
        if value in WEEKDAY_INDEX
    ]
    if task.frequency == "weekly" and not configured_days:
        configured_days = [local_reference.weekday()]
    if not configured_days:
        configured_days = [local_reference.weekday()]

    for day_offset in range(0, 8):
        candidate = occurrence(day_offset)
        if candidate.weekday() in configured_days and candidate > reference:
            return candidate
    return occurrence(7)


def count_verified_contactable_leads(
    run: ResearchRun,
    requirement: str,
    *,
    allow_network_unchecked_email: bool = False,
) -> int:
    candidates = ContactCandidate.objects.filter(
        lead__book__research_run=run,
    )
    qualification = Q(verification_status="verified")
    if allow_network_unchecked_email:
        qualification |= Q(
            channel="email",
            verification_status="other",
            verification_score__gte=75,
            deliverability_status="unknown",
        )
    candidates = candidates.filter(qualification)
    if requirement == "email_only":
        candidates = candidates.filter(channel="email")
    else:
        candidates = candidates.filter(Q(channel="email") | Q(channel="phone"))
    return candidates.values("lead_id").distinct().count()


def _lease_seconds() -> int:
    """Return a conservative bound before an abandoned task can be recovered."""

    return min(max(int(getattr(settings, "APP_SCHEDULED_TASK_LEASE_SECONDS", 6 * 60 * 60)), 60), 7 * 24 * 60 * 60)


def claim_scheduled_lead_task(task_id, *, force: bool) -> ScheduledLeadTask | None:
    """Atomically claim a due task, recovering only a clearly stale worker lease."""

    now = timezone.now()
    stale_before = now - timedelta(seconds=_lease_seconds())
    claimable = ScheduledLeadTask.objects.filter(pk=task_id).filter(
        Q(execution_status__in=["idle", "failed"])
        | Q(execution_status="running", last_started_at__isnull=True)
        | Q(execution_status="running", last_started_at__lt=stale_before)
    )
    if not force:
        claimable = claimable.filter(is_active=True).filter(
            Q(next_run_at__isnull=True) | Q(next_run_at__lte=now)
        )
    claimed = claimable.update(
        execution_status="running",
        last_started_at=now,
        last_error="",
    )
    if not claimed:
        return None
    return ScheduledLeadTask.objects.get(pk=task_id)


def execute_scheduled_lead_task(
    task_id,
    *,
    force: bool = False,
    preclaimed: bool = False,
) -> ResearchRun | None:
    """Claim and execute one scheduled hunt.

    The conditional update prevents a scheduler tick and a manual Run Now click
    from starting the same task concurrently.
    """

    if preclaimed:
        task = ScheduledLeadTask.objects.filter(pk=task_id, execution_status="running").first()
    else:
        task = claim_scheduled_lead_task(task_id, force=force)
    if task is None:
        return None

    target = min(max(int(task.target_verified_leads), 1), 200)
    hard_book_limit = min(max(int(getattr(settings, "APP_SCHEDULED_MAX_BOOKS", 700)), 1), 700)
    candidate_limit = min(max(target * 3, target), hard_book_limit)
    run = ResearchRun.objects.create(
        scheduled_task=task,
        keyword=task.keyword,
        source_provider=task.source_provider,
        marketplace="US",
        max_books=candidate_limit,
        settings_json={
            "scheduled_task_id": str(task.id),
            "only_new_books": task.only_new_books,
            "target_verified_leads": target,
            "require_contact": task.require_contact,
            "require_public_email": task.require_contact == "email_only",
            "verify_email_mx": task.verify_email_mx,
            "run_video_search": True,
            "run_groq_ai_extraction": True,
        },
    )

    try:
        run_research_pipeline(run.id)
        run.refresh_from_db()
        task.refresh_from_db()
        verified_count = count_verified_contactable_leads(
            run,
            task.require_contact,
            allow_network_unchecked_email=not task.verify_email_mx,
        )
        completed_at = timezone.now()
        ScheduledLeadTask.objects.filter(pk=task.id).update(
            execution_status="idle" if run.status != "failed" else "failed",
            last_run_at=completed_at,
            next_run_at=calculate_next_run_at(task, from_time=completed_at),
            total_runs_count=F("total_runs_count") + 1,
            total_verified_leads_found=F("total_verified_leads_found") + verified_count,
            last_error=run.error_message,
        )
        return run
    except Exception as exc:
        completed_at = timezone.now()
        run.refresh_from_db()
        if run.status not in {"completed", "canceled", "failed"}:
            run.mark_failed(str(exc))
        task.refresh_from_db()
        ScheduledLeadTask.objects.filter(pk=task.id).update(
            execution_status="failed",
            last_run_at=completed_at,
            next_run_at=calculate_next_run_at(task, from_time=completed_at),
            total_runs_count=F("total_runs_count") + 1,
            last_error=str(exc)[:5000],
        )
        raise
