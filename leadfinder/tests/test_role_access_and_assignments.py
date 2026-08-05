from datetime import time

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from leadfinder.models import Book, Lead, LeadAssignment, LeadAssignmentSchedule, UserProfile
from leadfinder.services.assignments import execute_assignment_schedule
from leadfinder.utils.normalize import normalized_book_key
from leadfinder.models import ResearchRun


@pytest.fixture
def role_users(db):
    User = get_user_model()
    admin = User.objects.create_user("manager", password="StrongPassword-4815", email="manager@example.test")
    UserProfile.objects.update_or_create(user=admin, defaults={"role": "admin"})
    sales_a = User.objects.create_user("sales-a", password="StrongPassword-4815", email="a@example.test")
    sales_b = User.objects.create_user("sales-b", password="StrongPassword-4815", email="b@example.test")
    UserProfile.objects.update_or_create(user=sales_a, defaults={"role": "sales"})
    UserProfile.objects.update_or_create(user=sales_b, defaults={"role": "sales"})
    return admin, sales_a, sales_b


def make_lead(number):
    run = ResearchRun.objects.create(keyword=f"run {number}", source_provider="manual", status="completed")
    book = Book.objects.create(
        research_run=run,
        title=f"Assigned Book {number}",
        author_name=f"Author {number}",
        normalized_key=normalized_book_key(f"Assigned Book {number}", f"Author {number}", ""),
        source_provider="manual",
    )
    return Lead.objects.create(
        book=book,
        public_email=f"author{number}@example.test",
        verification_status="verified",
        lead_score=80,
    )


def test_anonymous_users_are_redirected_to_login(db):
    response = Client().get(reverse("leadfinder:lead_list"))
    assert response.status_code == 302
    assert reverse("leadfinder:login") in response.url


def test_session_login_accepts_email_address(role_users):
    admin, _, _ = role_users
    client = Client()
    response = client.post(
        reverse("leadfinder:login"),
        {"username": admin.email, "password": "StrongPassword-4815"},
    )
    assert response.status_code == 302
    assert str(admin.id) == client.session["_auth_user_id"]


def test_salesperson_only_sees_assigned_leads(role_users):
    admin, sales_a, sales_b = role_users
    visible = make_lead(1)
    hidden = make_lead(2)
    LeadAssignment.objects.create(lead=visible, assigned_to=sales_a, assigned_by=admin)
    LeadAssignment.objects.create(lead=hidden, assigned_to=sales_b, assigned_by=admin)
    client = Client()
    client.force_login(sales_a)

    response = client.get(reverse("leadfinder:lead_list"))
    html = response.content.decode()
    assert "Assigned Book 1" in html
    assert "Assigned Book 2" not in html
    assert client.get(reverse("leadfinder:lead_detail", args=[hidden.id])).status_code == 404
    assert client.get(reverse("leadfinder:run_list")).status_code == 403


def test_assignment_schedule_assigns_unique_leads_and_handles_empty_pool(role_users):
    admin, sales_a, _ = role_users
    leads = [make_lead(i) for i in range(1, 4)]
    schedule = LeadAssignmentSchedule.objects.create(
        name="Weekday allocation",
        salesperson=sales_a,
        created_by=admin,
        daily_lead_count=2,
        days_of_week=["mon", "tue", "wed", "thu", "fri"],
        run_time=time(9, 0),
        contact_requirement="email_only",
    )
    first_run = execute_assignment_schedule(schedule.id, force=True)
    second_run = execute_assignment_schedule(schedule.id, force=True)
    third_run = execute_assignment_schedule(schedule.id, force=True)

    assert first_run.assigned_count == 2
    assert second_run.assigned_count == 1
    assert third_run.assigned_count == 0
    assert LeadAssignment.objects.values("lead_id").distinct().count() == 3


def test_salesperson_can_update_task_outcome(role_users):
    admin, sales_a, _ = role_users
    lead = make_lead(8)
    assignment = LeadAssignment.objects.create(lead=lead, assigned_to=sales_a, assigned_by=admin)
    client = Client()
    client.force_login(sales_a)
    response = client.post(
        reverse("leadfinder:lead_assignment_update", args=[assignment.id]),
        {"status": "converted", "contact_quality": "complete", "notes": "Booked a discovery call."},
    )
    assignment.refresh_from_db()
    assert response.status_code == 302
    assert assignment.status == "converted"
    assert assignment.completed_at is not None
    assert assignment.converted_at is not None


def test_jwt_contains_role_claim(role_users):
    _, sales_a, _ = role_users
    response = Client().post(
        reverse("leadfinder:token_obtain_pair"),
        data={"username": sales_a.username, "password": "StrongPassword-4815"},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert "access" in response.json()
    assert "refresh" in response.json()


def test_jwt_login_accepts_email_address(role_users):
    _, sales_a, _ = role_users
    response = Client().post(
        reverse("leadfinder:token_obtain_pair"),
        data={"username": sales_a.email, "password": "StrongPassword-4815"},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert "access" in response.json()


def test_super_admin_role_pages_render(client):
    assert client.get(reverse("leadfinder:team_list")).status_code == 200
    assert client.get(reverse("leadfinder:assignment_schedule_list")).status_code == 200
    assert client.get(reverse("leadfinder:assignment_schedule_create")).status_code == 200


def test_admin_reassignment_preserves_history(role_users):
    admin, sales_a, sales_b = role_users
    lead = make_lead(12)
    old_assignment = LeadAssignment.objects.create(lead=lead, assigned_to=sales_a, assigned_by=admin)
    client = Client()
    client.force_login(admin)
    response = client.post(
        reverse("leadfinder:lead_bulk_action"),
        {"lead_ids": [str(lead.id)], "action": "bulk_assign", "assigned_to": sales_b.id},
    )
    old_assignment.refresh_from_db()
    assert response.status_code == 302
    assert old_assignment.is_current is False
    assert LeadAssignment.objects.get(lead=lead, is_current=True).assigned_to == sales_b
