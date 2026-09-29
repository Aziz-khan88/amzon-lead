from datetime import datetime, time, timedelta

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from leadfinder.models import Book, ContactCandidate, Lead, ResearchRun, ScheduledLeadTask
from leadfinder.services.pipeline.run_research import _candidate_batch_for_run, run_research_pipeline
from leadfinder.services.pipeline.scheduled_executor import (
    calculate_next_run_at,
    claim_scheduled_lead_task,
    count_verified_contactable_leads,
    execute_scheduled_lead_task,
)
from leadfinder.utils.normalize import normalized_book_key


pytestmark = pytest.mark.django_db


def make_task(**overrides):
    values = {
        "name": "Children Illustration Hunt",
        "keyword": "children book illustration",
        "frequency": "daily",
        "run_time": time(8, 0),
        "target_verified_leads": 50,
        "next_run_at": timezone.now() - timedelta(minutes=1),
    }
    values.update(overrides)
    return ScheduledLeadTask.objects.create(**values)


def test_calculate_next_run_supports_daily_interval_and_specific_days():
    reference = timezone.make_aware(datetime(2026, 8, 3, 9, 0))  # Monday
    daily = ScheduledLeadTask(frequency="daily", run_time=time(8, 0))
    assert calculate_next_run_at(daily, from_time=reference) == timezone.make_aware(datetime(2026, 8, 4, 8, 0))

    interval = ScheduledLeadTask(frequency="interval_hours", interval_hours=12)
    assert calculate_next_run_at(interval, from_time=reference) == reference + timedelta(hours=12)

    specific = ScheduledLeadTask(frequency="specific_days", days_of_week=["wed", "fri"], run_time=time(10, 30))
    assert calculate_next_run_at(specific, from_time=reference) == timezone.make_aware(datetime(2026, 8, 5, 10, 30))


def test_scheduled_task_create_and_list_pages(client):
    response = client.post(
        reverse("leadfinder:scheduled_task_create"),
        {
            "name": "Children Illustration Hunt",
            "keyword": "children book illustration",
            "source_provider": "ddgs",
            "frequency": "specific_days",
            "interval_hours": 24,
            "days_of_week": ["mon", "wed", "fri"],
            "run_time": "08:00",
            "target_verified_leads": 50,
            "require_contact": "email_or_phone",
            "only_new_books": "on",
            "verify_email_mx": "on",
        },
    )

    assert response.status_code == 302
    task = ScheduledLeadTask.objects.get()
    assert task.days_of_week == ["mon", "wed", "fri"]
    assert task.next_run_at is not None

    list_response = client.get(reverse("leadfinder:scheduled_task_list"))
    html = list_response.content.decode()
    assert list_response.status_code == 200
    assert "Children Illustration Hunt" in html
    assert "New books only" in html
    assert "Target 50" in html


def test_schedule_requires_days_for_weekly_frequency(client):
    response = client.post(
        reverse("leadfinder:scheduled_task_create"),
        {
            "name": "Weekly hunt",
            "keyword": "picture book author",
            "source_provider": "ddgs",
            "frequency": "weekly",
            "interval_hours": 24,
            "run_time": "08:00",
            "target_verified_leads": 25,
            "require_contact": "email_only",
        },
    )
    assert response.status_code == 200
    assert "Select at least one day" in response.content.decode()


def test_pause_and_resume_recalculate_schedule(client):
    task = make_task()
    pause = client.post(reverse("leadfinder:scheduled_task_toggle", args=[task.id]))
    task.refresh_from_db()
    assert pause.status_code == 302
    assert task.is_active is False

    resume = client.post(reverse("leadfinder:scheduled_task_toggle", args=[task.id]))
    task.refresh_from_db()
    assert resume.status_code == 302
    assert task.is_active is True
    assert task.next_run_at > timezone.now()


def test_run_now_starts_background_launcher(client, monkeypatch):
    task = make_task()
    started = []
    monkeypatch.setattr("leadfinder.views._start_scheduled_task", lambda task_id: started.append(task_id))

    response = client.post(reverse("leadfinder:scheduled_task_run_now", args=[task.id]))
    assert response.status_code == 302
    assert started == [task.id]


def test_executor_updates_metrics_and_blocks_duplicate_claim(monkeypatch):
    task = make_task(target_verified_leads=25)

    def fake_pipeline(run_id):
        run = ResearchRun.objects.get(id=run_id)
        run.mark_running()
        book = Book.objects.create(
            research_run=run,
            title="A New Picture Book",
            author_name="Avery Author",
            asin="B0NEWBOOK1",
            normalized_key=normalized_book_key("A New Picture Book", "Avery Author", "B0NEWBOOK1"),
            source_provider="ddgs",
        )
        lead = Lead.objects.create(book=book)
        ContactCandidate.objects.create(
            lead=lead,
            channel="email",
            raw_value="hello@avery.example",
            normalized_value="hello@avery.example",
            verification_status="verified",
            verification_score=90,
        )
        run.mark_completed()

    monkeypatch.setattr("leadfinder.services.pipeline.scheduled_executor.run_research_pipeline", fake_pipeline)
    run = execute_scheduled_lead_task(task.id)
    task.refresh_from_db()

    assert run is not None
    assert run.scheduled_task == task
    assert task.execution_status == "idle"
    assert task.total_runs_count == 1
    assert task.total_verified_leads_found == 1
    assert task.next_run_at > timezone.now()

    task.execution_status = "running"
    task.save(update_fields=["execution_status", "updated_at"])
    assert execute_scheduled_lead_task(task.id, force=True) is None


@override_settings(APP_SCHEDULED_TASK_LEASE_SECONDS=60)
def test_stale_scheduler_claim_is_recovered_without_claiming_a_current_run():
    stale_task = make_task(
        execution_status="running",
        last_started_at=timezone.now() - timedelta(seconds=61),
    )
    active_task = make_task(
        execution_status="running",
        last_started_at=timezone.now() - timedelta(seconds=59),
    )

    claimed = claim_scheduled_lead_task(stale_task.id, force=False)

    assert claimed is not None
    stale_task.refresh_from_db()
    assert stale_task.execution_status == "running"
    assert stale_task.last_started_at > timezone.now() - timedelta(seconds=2)
    assert claim_scheduled_lead_task(active_task.id, force=True) is None


def test_scheduled_candidate_batch_excludes_prior_keys_and_asins():
    old_run = ResearchRun.objects.create(keyword="old", status="completed")
    Book.objects.create(
        research_run=old_run,
        title="Already Seen",
        author_name="Known Author",
        asin="B0EXISTING",
        normalized_key=normalized_book_key("Already Seen", "Known Author", "B0EXISTING"),
        source_provider="ddgs",
    )
    run = ResearchRun.objects.create(
        keyword="new",
        max_books=10,
        settings_json={"only_new_books": True},
    )
    candidates = [
        {"title": "Different Listing Title", "author_name": "Known Author", "asin": "B0EXISTING"},
        {"title": "Brand New Book", "author_name": "New Author", "asin": "B0BRANDNEW"},
    ]

    result = _candidate_batch_for_run(run, candidates)
    run.refresh_from_db()
    assert [item["asin"] for item in result] == ["B0BRANDNEW"]
    assert run.settings_json["scheduled_dedupe_skipped"] == 1


def test_network_unchecked_first_party_email_can_qualify_for_optional_mx_schedule():
    run = ResearchRun.objects.create(keyword="optional mx")
    book = Book.objects.create(
        research_run=run,
        title="Optional MX Book",
        author_name="Author",
        normalized_key="optional-mx-book",
        source_provider="ddgs",
    )
    lead = Lead.objects.create(book=book)
    ContactCandidate.objects.create(
        lead=lead,
        channel="email",
        raw_value="author@example.com",
        normalized_value="author@example.com",
        verification_status="other",
        verification_score=75,
        deliverability_status="unknown",
    )

    assert count_verified_contactable_leads(run, "email_only") == 0
    assert count_verified_contactable_leads(
        run,
        "email_only",
        allow_network_unchecked_email=True,
    ) == 1


def test_pipeline_stops_when_scheduled_verified_target_is_reached(monkeypatch):
    run = ResearchRun.objects.create(
        keyword="target test",
        max_books=2,
        settings_json={
            "target_verified_leads": 1,
            "require_contact": "email_or_phone",
            "verify_email_mx": False,
            "run_video_search": False,
            "run_groq_ai_extraction": False,
        },
    )

    def fake_discovery(active_run):
        return [
            Book.objects.create(
                research_run=active_run,
                title=f"Target Book {index}",
                author_name="Target Author",
                normalized_key=f"target-{index}",
                source_provider="ddgs",
            )
            for index in range(2)
        ]

    mx_flags = []

    def fake_process(book, *, run_video_search, run_ai_extraction, verify_email_mx):
        mx_flags.append(verify_email_mx)
        lead = Lead.objects.create(book=book)
        ContactCandidate.objects.create(
            lead=lead,
            channel="phone",
            raw_value="+12025550123",
            normalized_value="+12025550123",
            verification_status="verified",
            verification_score=90,
        )
        return lead

    monkeypatch.setattr("leadfinder.services.pipeline.run_research.discover_books_from_keyword", fake_discovery)
    monkeypatch.setattr("leadfinder.services.pipeline.run_research.process_book", fake_process)
    run_research_pipeline(run.id)
    run.refresh_from_db()

    assert run.status == "completed"
    assert Lead.objects.filter(book__research_run=run).count() == 1
    assert run.settings_json["scheduled_target_reached"] is True
    assert run.settings_json["scheduled_processed_books"] == 1
    assert mx_flags == [False]


def test_scheduler_command_runs_due_tasks(monkeypatch):
    task = make_task()
    created_run = ResearchRun.objects.create(keyword="scheduled", status="completed")
    called = []

    def fake_execute(task_id):
        called.append(task_id)
        return created_run

    monkeypatch.setattr(
        "leadfinder.management.commands.run_scheduler_loop.execute_scheduled_lead_task",
        fake_execute,
    )
    call_command("run_scheduler_loop")
    assert called == [task.id]


def test_scheduler_command_also_recovers_active_task_with_missing_next_run(monkeypatch):
    task = make_task(next_run_at=None)
    created_run = ResearchRun.objects.create(keyword="scheduled", status="completed")
    called = []

    def fake_execute(task_id):
        called.append(task_id)
        return created_run

    monkeypatch.setattr(
        "leadfinder.management.commands.run_scheduler_loop.execute_scheduled_lead_task",
        fake_execute,
    )
    call_command("run_scheduler_loop")

    assert called == [task.id]


def test_weekly_schedule_rejects_multiple_days(client):
    response = client.post(
        reverse("leadfinder:scheduled_task_create"),
        {
            "name": "Weekly hunt",
            "keyword": "picture book author",
            "source_provider": "ddgs",
            "frequency": "weekly",
            "days_of_week": ["mon", "wed"],
            "run_time": "08:00",
            "target_verified_leads": 25,
            "require_contact": "email_only",
        },
    )

    assert response.status_code == 200
    assert "Weekly schedules run on one day" in response.content.decode()
