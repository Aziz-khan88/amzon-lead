from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core.management import call_command

from leadfinder.models import AuthorProfile, Book, Evidence, Lead, ResearchRun, VerificationBatch
from leadfinder.services.crawl.social_contact_crawler import SocialContactPage
from leadfinder.services.social.profile_harvester import harvest_social_profiles
from leadfinder.services.verification.contact_verifier import verify_lead_contacts
from leadfinder.utils.normalize import normalized_book_key


@pytest.fixture
def verification_lead(db):
    run = ResearchRun.objects.create(keyword="picture book", source_provider="csv")
    book = Book.objects.create(
        research_run=run,
        title="The Moon Rabbit",
        author_name="Avery Moon",
        normalized_key=normalized_book_key("The Moon Rabbit", "Avery Moon", "B012345678"),
        source_provider="csv",
    )
    author = AuthorProfile.objects.create(
        author_name="Avery Moon",
        normalized_author_key="avery moon",
        canonical_website="https://averymoonbooks.com",
        identity_confidence=0.92,
    )
    return Lead.objects.create(book=book, author_profile=author, public_email="avery@averymoonbooks.com")


def _email_evidence(lead, source_url="https://averymoonbooks.com/contact"):
    return Evidence.objects.create(
        lead=lead,
        author_profile=lead.author_profile,
        evidence_type="contact_page",
        field_name="public_email",
        field_value="avery@averymoonbooks.com",
        source_url=source_url,
        source_title="Contact Avery Moon",
        source_snippet="Avery Moon author contact: avery@averymoonbooks.com",
        confidence=0.95,
        is_primary=True,
    )


@patch("leadfinder.services.verification.contact_verifier.check_deliverability")
def test_deliverable_first_party_email_becomes_verified(mock_delivery, verification_lead):
    mock_delivery.return_value = {"status": "deliverable", "message": "250 accepted", "mx_hosts": ["mx.example"]}
    _email_evidence(verification_lead)

    verify_lead_contacts(verification_lead)
    verification_lead.refresh_from_db()

    assert verification_lead.verification_status == "verified"
    assert verification_lead.verification_score >= 90
    assert verification_lead.primary_contact.normalized_value == "avery@averymoonbooks.com"
    assert verification_lead.contact_candidates.filter(is_primary=True).count() == 1


@patch("leadfinder.services.verification.contact_verifier.check_deliverability")
def test_catch_all_email_stays_other(mock_delivery, verification_lead):
    mock_delivery.return_value = {"status": "catch_all", "message": "all recipients accepted", "mx_hosts": ["mx.example"]}
    _email_evidence(verification_lead)

    verify_lead_contacts(verification_lead)
    verification_lead.refresh_from_db()

    assert verification_lead.verification_status == "other"
    assert verification_lead.primary_contact.deliverability_status == "catch_all"


def test_invalid_email_is_not_verified(verification_lead):
    verification_lead.public_email = "not-an-email"
    verification_lead.save(update_fields=["public_email"])

    verify_lead_contacts(verification_lead, check_network=False)
    verification_lead.refresh_from_db()

    assert verification_lead.verification_status == "not_verified"
    assert verification_lead.primary_contact.verification_status == "not_verified"


def test_public_social_profile_adds_audited_contact(verification_lead, monkeypatch):
    verification_lead.author_profile.instagram_url = "https://instagram.com/averymoonbooks"
    verification_lead.author_profile.save(update_fields=["instagram_url"])
    monkeypatch.setattr(
        "leadfinder.services.social.profile_harvester._public_profile_html",
        lambda url: (
            "Avery Moon Books",
            "Avery Moon writes The Moon Rabbit. Contact avery@averymoonbooks.com",
            ["https://averymoonbooks.com/contact"],
            url,
            "<html>Avery Moon avery@averymoonbooks.com</html>",
        ),
    )

    audits = harvest_social_profiles(verification_lead)

    assert len(audits) == 1
    assert audits[0].fetch_status == "fetched"
    assert audits[0].identity_score == 90
    assert Evidence.objects.filter(
        lead=verification_lead,
        evidence_type="social_profile",
        field_name="public_email",
        field_value="avery@averymoonbooks.com",
    ).exists()


def test_inaccessible_social_profile_is_recorded_as_blocked(verification_lead, monkeypatch):
    verification_lead.author_profile.linkedin_url = "https://linkedin.com/in/averymoon"
    verification_lead.author_profile.save(update_fields=["linkedin_url"])
    monkeypatch.setattr("leadfinder.services.social.profile_harvester._public_profile_html", lambda url: None)

    audits = harvest_social_profiles(verification_lead)

    assert audits[0].fetch_status == "blocked"
    assert audits[0].extracted_contacts_json == []


def test_social_profile_surname_only_does_not_create_contact(verification_lead, monkeypatch):
    verification_lead.author_profile.instagram_url = "https://instagram.com/unrelated"
    verification_lead.author_profile.save(update_fields=["instagram_url"])
    monkeypatch.setattr(
        "leadfinder.services.social.profile_harvester._public_profile_html",
        lambda url: (
            "Moon Publishing News",
            "News from Moon Publishing. Email wrong@example.com",
            [],
            url,
            "<html>Moon Publishing wrong@example.com</html>",
        ),
    )

    audit = harvest_social_profiles(verification_lead)[0]

    assert audit.identity_score == 30
    assert audit.extracted_contacts_json == []
    assert not Evidence.objects.filter(lead=verification_lead, field_name="public_email", field_value="wrong@example.com").exists()


def test_identity_matched_social_profile_crawls_linktree_contact_with_provenance(verification_lead, monkeypatch):
    verification_lead.author_profile.instagram_url = "https://instagram.com/averymoonbooks"
    verification_lead.author_profile.save(update_fields=["instagram_url"])
    monkeypatch.setattr(
        "leadfinder.services.social.profile_harvester._public_profile_html",
        lambda url: (
            "Avery Moon Books",
            "Avery Moon writes The Moon Rabbit.",
            ["https://linktr.ee/averymoonbooks"],
            url,
            "<html>Avery Moon</html>",
        ),
    )
    monkeypatch.setattr(
        "leadfinder.services.social.profile_harvester.crawl_social_contact_pages",
        lambda urls: [
            SocialContactPage(
                url="https://linktr.ee/averymoonbooks",
                title="Avery Moon | Links",
                text="For school visits contact Avery Moon.",
                links=[],
                emails=["booking@averymoonbooks.com"],
                phones=[],
            )
        ],
    )

    audit = harvest_social_profiles(verification_lead)[0]

    assert audit.extracted_contacts_json == [
        {
            "field": "public_email",
            "value": "booking@averymoonbooks.com",
            "source_url": "https://linktr.ee/averymoonbooks",
            "source_title": "Avery Moon | Links",
            "source_snippet": "Linked from the identity-matched instagram profile Avery Moon Books. For school visits contact Avery Moon.",
            "confidence": 0.82,
        }
    ]
    evidence = Evidence.objects.get(
        lead=verification_lead,
        field_name="public_email",
        field_value="booking@averymoonbooks.com",
    )
    assert evidence.source_url == "https://linktr.ee/averymoonbooks"
    assert "identity-matched instagram profile" in evidence.source_snippet


def test_batch_command_records_complete_counts(verification_lead):
    _email_evidence(verification_lead)

    call_command(
        "reverify_contacts",
        "--lead-id",
        str(verification_lead.id),
        "--no-social",
        "--no-network",
        verbosity=0,
    )

    batch = VerificationBatch.objects.get()
    assert batch.status == "completed"
    assert batch.total_count == 1
    assert batch.processed_count == 1
    assert batch.other_count == 1
    assert batch.error_count == 0
