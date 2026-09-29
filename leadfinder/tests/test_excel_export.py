import pytest
from django.utils import timezone
from leadfinder.models import Book, AuthorProfile, Lead, Evidence, SalesAgentBrief
from leadfinder.services.export.csv_export import build_leads_workbook


@pytest.mark.django_db
def test_build_leads_workbook():
    # Setup test research run
    from leadfinder.models import ResearchRun
    run = ResearchRun.objects.create(
        keyword="friendship picture book",
        source_provider="ddgs",
        status="completed"
    )

    # Setup test book
    book = Book.objects.create(
        research_run=run,
        title="The Friendly Bear",
        author_name="Jane Doe",
        asin="B012345678",
        amazon_book_url="https://www.amazon.com/dp/B012345678",
        category="Children's Picture Books",
        review_count=15,
        rating=4.6,
        publisher="Independently published",
        publication_date="2025-01-01",
        cover_image_url="https://images.example.com/bear.jpg",
        has_aplus_content=False,
    )

    # Setup test author profile
    author = AuthorProfile.objects.create(
        author_name="Jane Doe",
        normalized_author_key="jane_doe",
        canonical_website="https://janedoe.example",
        contact_page_url="https://janedoe.example/contact",
        instagram_url="https://instagram.com/janedoe",
        facebook_url="https://facebook.com/janedoe",
        identity_confidence=0.9,
    )

    # Setup test lead
    lead = Lead.objects.create(
        book=book,
        author_profile=author,
        public_email="jane@janedoe.example",
        location="New York, NY",
        lead_score=85,
        lead_tier="hot",
        video_status="no_public_video_found",
        manual_review_status="needs_review",
        service_needs_json=["A+ Content", "Website development"],
        fit_reason="Excellent lead fit.",
        suggested_pitch_angle="A+ Content opportunity",
        what_to_say="Pitch cover design and Amazon marketing.",
    )

    # Setup evidence
    Evidence.objects.create(
        lead=lead,
        book=book,
        author_profile=author,
        evidence_type="contact_page",
        field_name="public_email",
        field_value="jane@janedoe.example",
        source_url="https://janedoe.example/contact",
        source_title="Contact Jane Doe",
        confidence=0.95,
        is_primary=True,
    )

    # Setup brief
    SalesAgentBrief.objects.create(
        lead=lead,
        brief_markdown="## Sales Brief",
        pitch_direct="Direct pitch copy",
        pitch_agent="Agent pitch copy",
        pitch_publicist="Publicist pitch copy",
    )

    # Act: generate the Excel workbook
    queryset = Lead.objects.filter(id=lead.id)
    wb = build_leads_workbook(queryset)

    # Assert workbook worksheets
    assert wb is not None
    assert set(wb.sheetnames) == {"Authors", "Books", "Contact Evidence", "Outreach Log"}

    # Assert Tab 1: Authors contents
    ws1 = wb["Authors"]
    assert ws1.max_row == 2
    assert ws1.cell(row=1, column=1).value == "Lead ID"
    assert ws1.cell(row=1, column=3).value == "Author Name"
    assert ws1.cell(row=2, column=3).value == "Jane Doe"
    assert ws1.cell(row=2, column=10).value == "jane@janedoe.example"
    assert ws1.cell(row=2, column=20).value == "Other"
    assert ws1.cell(row=2, column=21).value == 0

    # Assert Tab 2: Books contents
    ws2 = wb["Books"]
    assert ws2.max_row == 2
    assert ws2.cell(row=1, column=2).value == "Book Title"
    assert ws2.cell(row=2, column=2).value == "The Friendly Bear"
    assert ws2.cell(row=2, column=3).value == "B012345678"
    assert ws2.cell(row=2, column=14).value == "No"  # has_aplus_content=False mapped to No
    assert ws2.cell(row=2, column=15).value == "A+ Content, Website development"

    # Assert Tab 3: Contact Evidence contents
    ws3 = wb["Contact Evidence"]
    assert ws3.max_row == 2
    assert ws3.cell(row=1, column=2).value == "Contact Type"
    assert ws3.cell(row=2, column=2).value == "public_email"
    assert ws3.cell(row=2, column=3).value == "jane@janedoe.example"

    # Assert Tab 4: Outreach Log contents
    ws4 = wb["Outreach Log"]
    assert ws4.max_row == 2
    assert ws4.cell(row=1, column=2).value == "Outreach Angle"
    assert ws4.cell(row=2, column=2).value == "A+ Content opportunity"
    assert ws4.cell(row=2, column=12).value == "Direct pitch copy"
