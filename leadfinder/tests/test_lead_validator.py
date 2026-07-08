from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
import dns.resolver

from leadfinder.services.pipeline.lead_validator import is_valid_email, validate_phone_number, is_highly_valid_contact_email


def test_validate_phone_number_valid():
    # Valid US numbers format E164
    assert validate_phone_number("206-555-0100") == "+12065550100"
    assert validate_phone_number("+1 (206) 555-0100") == "+12065550100"
    # Valid international number (UK)
    assert validate_phone_number("+44 20 7946 0967") == "+442079460967"


def test_validate_phone_number_invalid():
    # Invalid numbers return None
    assert validate_phone_number("123") is None
    assert validate_phone_number("not-a-phone-number") is None
    assert validate_phone_number("") is None


def test_is_valid_email_syntax_invalid():
    assert is_valid_email("plainaddress") is False
    assert is_valid_email("@missinguser.com") is False
    assert is_valid_email("user@.com") is False


def test_is_valid_email_dummy_blocked():
    assert is_valid_email("author@example.com") is False
    assert is_valid_email("info@yourdomain.com") is False
    assert is_valid_email("placeholder@email.com") is False


@patch("leadfinder.services.pipeline.mx_validator.check_deliverability")
@patch("dns.resolver.Resolver.resolve")
def test_is_valid_email_dns_success(mock_resolve, mock_check):
    mock_check.return_value = {"status": "deliverable", "syntax_valid": True}
    # Mock Resolver.resolve to return a non-empty list of MX records
    mock_resolve.return_value = ["mock_mx_record"]
    
    assert is_valid_email("test@google.com") is True
    mock_resolve.assert_called_with("google.com", "MX")


@patch("leadfinder.services.pipeline.mx_validator.check_deliverability")
@patch("dns.resolver.Resolver.resolve")
def test_is_valid_email_dns_mx_no_answer_fallback_a_success(mock_resolve, mock_check):
    mock_check.return_value = {"status": "unknown", "syntax_valid": True}
    # First call for MX raises NoAnswer, second call for A returns A records
    mock_resolve.side_effect = [
        dns.resolver.NoAnswer(),
        ["mock_a_record"]
    ]
    
    assert is_valid_email("test@no-mx-fallback-a.com") is True
    # Ensure it checked both MX and A records
    assert mock_resolve.call_count == 2


@patch("dns.resolver.Resolver.resolve")
def test_is_valid_email_dns_failed_completely(mock_resolve):
    # Resolver throws NXDOMAIN for both MX and A queries
    mock_resolve.side_effect = dns.resolver.NXDOMAIN()
    
    assert is_valid_email("test@nonexistent-domain-fake-123.org") is False


def test_is_highly_valid_contact_email():
    # Patch resolve to return A/MX records for testing
    with patch("dns.resolver.Resolver.resolve") as mock_resolve, \
         patch("leadfinder.services.pipeline.mx_validator.check_deliverability") as mock_check:
        mock_resolve.return_value = ["mock_record"]
        mock_check.return_value = {"status": "deliverable", "syntax_valid": True}
        
        # Valid personal / agency / publisher emails
        assert is_highly_valid_contact_email("author@gmail.com") is True
        assert is_highly_valid_contact_email("info@averymoonbooks.com") is True
        assert is_highly_valid_contact_email("contact@literaryagency.com") is True
        assert is_highly_valid_contact_email("publicist@penguinrandomhouse.com") is True
        
        # Untrusted platform / builder hosting domains
        assert is_highly_valid_contact_email("author@wordpress.com") is False
        assert is_highly_valid_contact_email("author@wix.com") is False
        assert is_highly_valid_contact_email("author@blogspot.com") is False
        assert is_highly_valid_contact_email("author@blogger.com") is False
        assert is_highly_valid_contact_email("store@shopify.com") is False
        
        # Untrusted generic tech/corporate support desks
        assert is_highly_valid_contact_email("support@averymoonbooks.com") is False
        assert is_highly_valid_contact_email("help@averymoonbooks.com") is False
        assert is_highly_valid_contact_email("webmaster@averymoonbooks.com") is False
        assert is_highly_valid_contact_email("no-reply@averymoonbooks.com") is False


@pytest.mark.django_db
@patch("leadfinder.services.pipeline.mx_validator.check_deliverability")
@patch("dns.resolver.Resolver.resolve")
def test_validate_lead_compliance_basic(mock_resolve, mock_check):
    mock_resolve.return_value = ["mock_record"]
    mock_check.return_value = {"status": "deliverable", "syntax_valid": True}
    
    from leadfinder.models import Book, AuthorProfile, Lead, Evidence, ResearchRun
    from leadfinder.services.pipeline.lead_validator import validate_lead_compliance
    from leadfinder.utils.normalize import normalized_book_key

    run = ResearchRun.objects.create(keyword="test", source_provider="csv")
    book = Book.objects.create(
        research_run=run,
        title="Super Bunny",
        author_name="Alice Bunny",
        normalized_key=normalized_book_key("Super Bunny", "Alice Bunny", "B012345679"),
        source_provider="csv",
    )
    author = AuthorProfile.objects.create(
        author_name="Alice Bunny",
        normalized_author_key="alice bunny",
        identity_confidence=0.8,
    )
    lead = Lead.objects.create(
        book=book,
        author_profile=author,
        public_email="alice@bunny.com",
    )
    
    # 1. Missing evidence should trigger error
    errors = validate_lead_compliance(lead)
    assert any("missing registered public source URL evidence" in err for err in errors)

    # 2. Add valid evidence with source_url
    Evidence.objects.create(
        lead=lead,
        field_name="public_email",
        field_value="alice@bunny.com",
        source_url="https://bunny.com/contact",
        confidence=0.9,
    )
    errors = validate_lead_compliance(lead)
    assert not errors, f"Expected no compliance errors, got {errors}"

    # 3. Do not contact trigger
    lead.do_not_contact = True
    errors = validate_lead_compliance(lead)
    assert any("Opted Out" in err for err in errors)
