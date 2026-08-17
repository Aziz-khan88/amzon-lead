from __future__ import annotations

from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from leadfinder.models import (
    Lead,
    LeadAssignment,
    LeadAssignmentSchedule,
    LeadAssignmentScheduleRun,
)
from leadfinder.services.eligibility import EligibilityPolicy


WEEKDAY_INDEX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def calculate_next_assignment_at(schedule: LeadAssignmentSchedule, *, from_time=None):
    reference = from_time or timezone.now()
    local_reference = timezone.localtime(reference)
    current_tz = timezone.get_current_timezone()
    weekdays = [WEEKDAY_INDEX[value] for value in schedule.days_of_week if value in WEEKDAY_INDEX]
    weekdays = weekdays or list(range(7))
    for day_offset in range(0, 8):
        local_date = local_reference.date() + timedelta(days=day_offset)
        candidate = timezone.make_aware(datetime.combine(local_date, schedule.run_time), current_tz)
        if candidate.weekday() in weekdays and candidate > reference:
            return candidate
    return reference + timedelta(days=1)


def eligible_leads(schedule: LeadAssignmentSchedule):
    leads = Lead.objects.filter(do_not_contact=False).exclude(assignments__is_current=True)
    leads = leads.filter(lead_score__gte=schedule.minimum_lead_score)
    if schedule.verified_only:
        leads = EligibilityPolicy.verified_ready(leads)

    has_email = Q(public_email__gt="") | Q(representation_email__gt="") | Q(publicist_email__gt="")
    has_phone = Q(public_phone__gt="")
    if schedule.contact_requirement == "email_or_phone":
        leads = leads.filter(has_email | has_phone)
    elif schedule.contact_requirement == "email_only":
        leads = leads.filter(has_email)
    elif schedule.contact_requirement == "phone_only":
        leads = leads.filter(has_phone)
    elif schedule.contact_requirement == "email_and_phone":
        leads = leads.filter(has_email & has_phone)
    elif schedule.contact_requirement == "verified_contact":
        leads = EligibilityPolicy.verified_ready(leads)
    return leads.order_by("-verification_score", "-lead_score", "created_at")


@transaction.atomic
def assign_leads(*, lead_ids, salesperson, assigned_by=None, schedule=None, replace_current=False) -> int:
    if not salesperson.is_active:
        return 0
    leads = Lead.objects.select_for_update().filter(pk__in=list(lead_ids), do_not_contact=False)
    current = LeadAssignment.objects.select_for_update().filter(lead_id__in=leads.values("pk"), is_current=True)
    if replace_current:
        current.update(is_current=False)
        already_assigned = LeadAssignment.objects.none().values("lead_id")
    else:
        already_assigned = current.values("lead_id")
    assignments = [
        LeadAssignment(
            lead=lead,
            assigned_to=salesperson,
            assigned_by=assigned_by,
            schedule=schedule,
        )
        for lead in leads.exclude(pk__in=already_assigned)
    ]
    LeadAssignment.objects.bulk_create(assignments, ignore_conflicts=True)
    return len(assignments)


@transaction.atomic
def execute_assignment_schedule(schedule_id, *, force=False):
    now = timezone.now()
    schedule = LeadAssignmentSchedule.objects.select_for_update().select_related("salesperson", "created_by").get(pk=schedule_id)
    if not force and (not schedule.is_active or (schedule.next_run_at and schedule.next_run_at > now)):
        return None

    run = LeadAssignmentScheduleRun.objects.create(schedule=schedule, requested_count=schedule.daily_lead_count)
    try:
        lead_ids = list(eligible_leads(schedule).select_for_update()[: schedule.daily_lead_count].values_list("pk", flat=True))
        assigned_count = assign_leads(
            lead_ids=lead_ids,
            salesperson=schedule.salesperson,
            assigned_by=schedule.created_by,
            schedule=schedule,
        )
        completed_at = timezone.now()
        message = (
            f"Assigned {assigned_count} unique lead{'s' if assigned_count != 1 else ''}."
            if assigned_count
            else "No eligible unassigned leads were available; nothing was assigned."
        )
        run.status = "completed"
        run.assigned_count = assigned_count
        run.message = message
        run.completed_at = completed_at
        run.save(update_fields=["status", "assigned_count", "message", "completed_at", "updated_at"])
        LeadAssignmentSchedule.objects.filter(pk=schedule.pk).update(
            last_run_at=completed_at,
            next_run_at=calculate_next_assignment_at(schedule, from_time=completed_at),
            total_assigned=F("total_assigned") + assigned_count,
        )
        return run
    except Exception as exc:
        run.status = "failed"
        run.message = str(exc)[:500]
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "message", "completed_at", "updated_at"])
        raise
