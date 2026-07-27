import pytest

from leadfinder.models import AuthorProfile, Book, Evidence, Lead, ResearchRun
from leadfinder.services.pipeline.quality_gate import can_approve_lead
from leadfinder.utils.normalize import normalized_book_key


@pytest.fixture
def lead(db):
    run = ResearchRun.objects.create(keyword="demo", source_provider="csv")
    book = Book.objects.create(
        research_run=run,
        title="The Moonlit Bunny Adventure",
        author_name="Avery Moon",
        amazon_book_url="https://www.amazon.com/dp/B012345678",
        amazon_source_url="uploaded_csv/manual",
        normalized_key=normalized_book_key("The Moonlit Bunny Adventure", "Avery Moon", "B012345678"),
        source_provider="csv",
    )
    author = AuthorProfile.objects.create(
        author_name="Avery Moon",
        normalized_author_key="avery moon",
        canonical_website="https://avery.example",
        contact_page_url="https://avery.example/contact",
        identity_confidence=0.9,
    )
    lead = Lead.objects.create(
        book=book,
        author_profile=author,
        public_email="hello@avery.example",
        video_status="no_public_video_found",
    )
    Evidence.objects.create(
        lead=lead,
        field_name="public_email",
        field_value="hello@avery.example",
        evidence_type="contact_page",
        source_url="https://avery.example/contact",
        confidence=0.9,
    )
    return lead


def test_cannot_approve_lead_without_source_urls(lead):
    lead.evidence.all().delete()
    ok, errors = can_approve_lead(lead)
    assert not ok
    assert any("source URL" in error for error in errors)


def test_cannot_approve_do_not_contact_lead(lead):
    lead.do_not_contact = True
    lead.save()
    ok, errors = can_approve_lead(lead)
    assert not ok
    assert any("do-not-contact" in error for error in errors)


def test_cannot_approve_identity_unclear_without_override(lead):
    lead.author_profile.identity_confidence = 0.2
    lead.author_profile.save()
    ok, errors = can_approve_lead(lead)
    assert not ok
    assert any("identity" in error.lower() for error in errors)


def test_cannot_approve_email_with_only_search_snippet_source(lead):
    lead.evidence.all().delete()
    Evidence.objects.create(
        lead=lead,
        field_name="public_email",
        field_value=lead.public_email,
        evidence_type="web_search_result",
        source_url="https://search.example/result",
        confidence=0.55,
    )

    ok, errors = can_approve_lead(lead)

    assert not ok
    assert any("high-confidence" in error for error in errors)


def test_required_amazon_url_rejects_spoofed_marketplace(lead):
    lead.book.amazon_book_url = "https://amazon.com.evil.example/dp/B012345678"
    lead.book.save(update_fields=["amazon_book_url"])

    ok, errors = can_approve_lead(lead)

    assert not ok
    assert any("verified Amazon marketplace" in error for error in errors)


def test_required_amazon_url_rejects_identifier_mismatch(lead):
    lead.book.asin = "B098765432"
    lead.book.amazon_book_url = "https://www.amazon.com/dp/B012345678"
    lead.book.save(update_fields=["asin", "amazon_book_url"])

    ok, errors = can_approve_lead(lead)

    assert not ok
    assert any("verified Amazon marketplace" in error for error in errors)
