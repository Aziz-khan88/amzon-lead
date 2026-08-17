from __future__ import annotations

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import Workbook

from leadfinder.models import AuthorProfile, Book, ContactCandidate, Evidence, Lead, ResearchRun
from leadfinder.services.export.csv_export import export_leads_xlsx
from leadfinder.services.eligibility import EligibilityPolicy
from leadfinder.utils.normalize import normalized_author_key, normalized_book_key
from leadfinder.views import parse_import_file


def _batch_workbook_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Batch 001"
    sheet.append(["Client batch - manual import"])
    sheet.append(["Source linked lead data"])
    sheet.append([
        "Batch ID", "Book / Project", "Author / Owner", "Phone", "Primary Email", "Amazon / Book URL",
        "Proof URL", "Verification Level", "Email Source URL", "Phone Source URL", "Notes",
    ])
    sheet.append([
        "B001", "Moonlight Garden", "Avery Moon", "+1 415 555 2671", "avery@example.com",
        "https://www.amazon.com/dp/B012345678", "https://avery.example/contact", "Needs review",
        "https://avery.example/contact", "https://avery.example/contact", "Imported from client batch",
    ])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_parse_excel_finds_header_after_title_rows():
    upload = SimpleUploadedFile(
        "batch.xlsx", _batch_workbook_bytes(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    rows, source = parse_import_file(upload)

    assert source == "Excel: Batch 001"
    assert len(rows) == 1
    assert rows[0]["book project"] == "Moonlight Garden"
    assert rows[0]["primary email"] == "avery@example.com"


def test_parse_app_xlsx_export_reassembles_author_book_and_contact_tabs(db):
    run = ResearchRun.objects.create(keyword="Export test", source_provider="manual", status="completed")
    book = Book.objects.create(
        research_run=run,
        title="Exportable Book",
        author_name="Robin Writer",
        asin="B012345678",
        amazon_book_url="https://www.amazon.com/dp/B012345678",
        normalized_key=normalized_book_key("Exportable Book", "Robin Writer", "B012345678"),
        source_provider="manual",
    )
    author = AuthorProfile.objects.create(
        author_name="Robin Writer",
        normalized_author_key=normalized_author_key("Robin Writer"),
        canonical_website="https://robin.example",
        contact_page_url="https://robin.example/contact",
    )
    lead = Lead.objects.create(book=book, author_profile=author, public_email="hello@robin.example")
    Evidence.objects.create(
        lead=lead,
        book=book,
        author_profile=author,
        evidence_type="manual",
        field_name="public_email",
        field_value="hello@robin.example",
        source_url="https://robin.example/contact",
        confidence=0.8,
    )
    response = export_leads_xlsx(Lead.objects.filter(pk=lead.pk))
    upload = SimpleUploadedFile("book_trailer_leads.xlsx", response.content)

    rows, source = parse_import_file(upload)

    assert source == "Excel: formatted app export"
    assert len(rows) == 1
    assert rows[0]["book title"] == "Exportable Book"
    assert rows[0]["author name"] == "Robin Writer"
    assert rows[0]["public email"] == "hello@robin.example"
    assert rows[0]["email source url"] == "https://robin.example/contact"


def test_manual_excel_import_creates_attested_leads_without_background_ai_or_checks(client, db, monkeypatch):
    started = []
    monkeypatch.setattr("leadfinder.views._start_manual_import_checks", lambda run_id: started.append(run_id))
    upload = SimpleUploadedFile(
        "batch.xlsx", _batch_workbook_bytes(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    response = client.post(reverse("leadfinder:import_csv"), {"csv_file": upload})

    assert response.status_code == 302
    assert started == []
    run = ResearchRun.objects.get(source_provider="manual")
    assert run.status == "completed"
    assert run.settings_json["run_groq_ai_extraction"] is False
    assert run.settings_json["verify_imported_contacts"] is False
    lead = Lead.objects.get(book__research_run=run)
    assert lead.book.title == "Moonlight Garden"
    assert lead.book.author_name == "Avery Moon"
    assert lead.public_email == "avery@example.com"
    assert lead.public_phone == "+1 415 555 2671"
    assert lead.verification_status == "other"
    assert lead.verification_score == 0
    assert lead.manual_review_status == "needs_review"
    assert lead.uploader_attested is True
    assert lead.uploader_attested_at is not None
    assert EligibilityPolicy.evaluate(lead).is_verified_ready is False
    assert lead.primary_contact is not None
    assert lead.primary_contact.channel == "email"
    assert lead.primary_contact.verification_status == "other"
    assert ContactCandidate.objects.filter(lead=lead, channel="phone", verification_status="other").exists()
    assert lead.author_profile.contact_page_url == "https://avery.example/contact"
    assert Evidence.objects.filter(lead=lead, field_name="public_email", source_url="https://avery.example/contact").exists()


def test_manual_import_starts_only_selected_optional_checks(client, db, monkeypatch):
    started = []
    monkeypatch.setattr("leadfinder.views._start_manual_import_checks", lambda run_id: started.append(run_id))
    upload = SimpleUploadedFile(
        "leads.csv",
        b"book_title,author_name,public_email,public_email_source_url\nSunny Day,Casey Ray,casey@example.com,https://casey.example/contact\n",
        content_type="text/csv",
    )

    response = client.post(
        reverse("leadfinder:import_csv"),
        {"csv_file": upload, "verify_imported_contacts": "on", "run_groq_ai_extraction": "on"},
    )

    assert response.status_code == 302
    run = ResearchRun.objects.get(source_provider="manual")
    assert started == [run.id]
    assert run.status == "pending"
    assert run.settings_json["verify_imported_contacts"] is True
    assert run.settings_json["run_groq_ai_extraction"] is True


def test_manual_import_preview_does_not_write_records(client, db):
    upload = SimpleUploadedFile("batch.xlsx", _batch_workbook_bytes())

    response = client.post(reverse("leadfinder:import_csv"), {"csv_file": upload, "preview": "1"})

    assert response.status_code == 200
    assert b"Detected preview" in response.content
    assert b"Moonlight Garden" in response.content
    assert ResearchRun.objects.count() == 0
