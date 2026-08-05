from __future__ import annotations

import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone

from leadfinder.models import LeadAssignmentSchedule, ScheduledLeadTask
from leadfinder.services.assignments import execute_assignment_schedule
from leadfinder.services.pipeline.scheduled_executor import execute_scheduled_lead_task


class Command(BaseCommand):
    help = "Run due scheduled lead hunts once, or continuously with --daemon."

    def add_arguments(self, parser):
        parser.add_argument(
            "--daemon",
            action="store_true",
            help="Keep checking for due tasks until the process is stopped.",
        )
        parser.add_argument(
            "--check-interval",
            type=int,
            default=60,
            help="Seconds between checks in daemon mode (default: 60).",
        )

    def handle(self, *args, **options):
        interval = options["check_interval"]
        if interval < 1 or interval > 3600:
            raise CommandError("--check-interval must be between 1 and 3600 seconds.")

        self.stdout.write("Scheduled lead task runner started.")
        try:
            while True:
                self.run_due_tasks()
                if not options["daemon"]:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Scheduler stopped."))
        finally:
            close_old_connections()

    def run_due_tasks(self) -> int:
        close_old_connections()
        due_ids = list(
            ScheduledLeadTask.objects.filter(
                is_active=True,
            )
            .filter(
                Q(next_run_at__isnull=True) | Q(next_run_at__lte=timezone.now())
            )
            .order_by("next_run_at")
            .values_list("id", flat=True)
        )
        completed = 0
        for task_id in due_ids:
            close_old_connections()
            try:
                run = execute_scheduled_lead_task(task_id)
                if run is None:
                    continue
                completed += 1
                self.stdout.write(
                    self.style.SUCCESS(f"Completed task {task_id} with run {run.id} ({run.status}).")
                )
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Task {task_id} failed: {exc}"))
            finally:
                close_old_connections()
        assignment_ids = list(
            LeadAssignmentSchedule.objects.filter(is_active=True)
            .filter(Q(next_run_at__isnull=True) | Q(next_run_at__lte=timezone.now()))
            .order_by("next_run_at")
            .values_list("id", flat=True)
        )
        for schedule_id in assignment_ids:
            close_old_connections()
            try:
                run = execute_assignment_schedule(schedule_id)
                if run is not None:
                    completed += 1
                    self.stdout.write(self.style.SUCCESS(f"Assignment schedule {schedule_id}: {run.message}"))
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Assignment schedule {schedule_id} failed: {exc}"))
            finally:
                close_old_connections()
        if not due_ids and not assignment_ids:
            self.stdout.write("No scheduled lead or assignment tasks are due.")
        return completed
