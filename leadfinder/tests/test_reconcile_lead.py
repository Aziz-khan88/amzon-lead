from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from leadfinder.services.ai.reconcile_lead import reconcile_and_verify_lead


def test_reconcile_and_verify_lead_pass_through():
    # When use_ai is False, only source-backed values pass through.
    gathered_contacts = {
        "public_email": "hello@janedoe.com",
        "public_phone": "+12065550100",
        "representation_email": "agent@literaryagency.com",
        "publicist_email": "pr@janedoepublisher.com",
    }
    evidence = [
        {
            "evidence_type": "contact_page",
            "field_name": "public_email",
            "field_value": "hello@janedoe.com",
            "source_url": "https://janedoe.com/contact",
            "source_title": "Jane Doe - Contact",
            "source_snippet": "Contact Jane Doe at hello@janedoe.com or +1 206-555-0100.",
        },
        {
            "evidence_type": "contact_page",
            "field_name": "public_phone",
            "field_value": "+12065550100",
            "source_url": "https://janedoe.com/contact",
            "source_title": "Jane Doe - Contact",
            "source_snippet": "Contact Jane Doe at hello@janedoe.com or +1 206-555-0100.",
        },
        {
            "evidence_type": "publisher_site",
            "field_name": "representation_email",
            "field_value": "agent@literaryagency.com",
            "source_url": "https://literaryagency.com/authors/jane-doe",
            "source_title": "Jane Doe representation",
            "source_snippet": "Jane Doe is represented by agent@literaryagency.com.",
        },
        {
            "evidence_type": "publisher_site",
            "field_name": "publicist_email",
            "field_value": "pr@janedoepublisher.com",
            "source_url": "https://janedoepublisher.com/jane-doe",
            "source_title": "Jane Doe publicity",
            "source_snippet": "For Jane Doe publicity email pr@janedoepublisher.com.",
        },
    ]
    
    result = reconcile_and_verify_lead(
        author_name="Jane Doe",
        book_title="My First Novel",
        gathered_contacts=gathered_contacts,
        all_evidence=evidence,
        use_ai=False,
    )
    
    assert result["verified_public_email"] == "hello@janedoe.com"
    assert result["verified_public_phone"] == "+12065550100"
    assert result["verified_representation_email"] == "agent@literaryagency.com"
    assert result["verified_publicist_email"] == "pr@janedoepublisher.com"
    assert result["is_identity_verified"] is True
    assert result["identity_verification_score"] == 0.7
    assert "Pass-through" in result["identity_verification_reason"]


@patch("leadfinder.services.ai.reconcile_lead.GroqJSONClient.complete_json")
def test_reconcile_and_verify_lead_ai_success(mock_complete):
    # Set up mocked AI response
    mock_complete.return_value = {
        "verified_public_email": "jane.doe@gmail.com",
        "verified_public_phone": "206-555-0100",
        "verified_representation_email": "agent@literaryagency.com",
        "verified_publicist_email": None,
        "is_identity_verified": True,
        "identity_verification_score": 0.95,
        "identity_verification_reason": "Matches official domain and social profile snippets perfectly.",
        "reconciliation_fixes": ["Healed email from snippet"],
    }
    
    gathered_contacts = {
        "public_email": None,
        "public_phone": None,
        "representation_email": None,
        "publicist_email": None,
    }
    evidence = [
        {
            "evidence_type": "contact_page",
            "field_name": "public_email",
            "field_value": "jane.doe@gmail.com",
            "source_url": "https://janedoe.com/contact",
            "source_title": "Jane Doe - Contact",
            "source_snippet": "Reach out to me at jane.doe@gmail.com",
        },
        {
            "evidence_type": "contact_page",
            "field_name": "public_phone",
            "field_value": "+12065550100",
            "source_url": "https://janedoe.com/contact",
            "source_title": "Jane Doe - Contact",
            "source_snippet": "Call Jane Doe at 206-555-0100.",
        },
        {
            "evidence_type": "publisher_site",
            "field_name": "representation_email",
            "field_value": "agent@literaryagency.com",
            "source_url": "https://literaryagency.com/authors/jane-doe",
            "source_title": "Jane Doe representation",
            "source_snippet": "Jane Doe is represented by agent@literaryagency.com.",
        }
    ]
    
    with patch("dns.resolver.Resolver.resolve") as mock_resolve:
        mock_resolve.return_value = ["mock_record"]
        result = reconcile_and_verify_lead(
            author_name="Jane Doe",
            book_title="My First Novel",
            gathered_contacts=gathered_contacts,
            all_evidence=evidence,
            use_ai=True,
        )
        
    assert result["verified_public_email"] == "jane.doe@gmail.com"
    assert result["verified_public_phone"] == "+12065550100"
    assert result["verified_representation_email"] == "agent@literaryagency.com"
    assert result["verified_publicist_email"] is None
    assert result["is_identity_verified"] is True
    assert result["identity_verification_score"] == 0.95
    assert "Matches official domain" in result["identity_verification_reason"]
    assert "Healed email from snippet" in result["reconciliation_fixes"]


@patch("leadfinder.services.ai.reconcile_lead.GroqJSONClient.complete_json")
def test_reconcile_and_verify_lead_ai_purges_untrusted(mock_complete):
    # Set up mocked AI response attempting to return an untrusted platform email and invalid phone
    mock_complete.return_value = {
        "verified_public_email": "jane@wordpress.com",  # wordpress.com is untrusted
        "verified_public_phone": "123",  # invalid format
        "verified_representation_email": "support@literaryagency.com",  # support@ is untrusted
        "verified_publicist_email": "jane@wix.com",  # wix.com is untrusted
        "is_identity_verified": True,
        "identity_verification_score": 0.8,
        "identity_verification_reason": "AI verified, but program should filter",
        "reconciliation_fixes": [],
    }
    
    gathered_contacts = {
        "public_email": None,
        "public_phone": None,
        "representation_email": None,
        "publicist_email": None,
    }
    
    with patch("dns.resolver.Resolver.resolve") as mock_resolve:
        mock_resolve.return_value = ["mock_record"]
        result = reconcile_and_verify_lead(
            author_name="Jane Doe",
            book_title="My First Novel",
            gathered_contacts=gathered_contacts,
            all_evidence=[],
            use_ai=True,
        )
        
    # Standard email/phone validation should programmatic filter untrusted domains / invalid structures
    assert result["verified_public_email"] is None
    assert result["verified_public_phone"] is None
    assert result["verified_representation_email"] is None
    assert result["verified_publicist_email"] is None
    assert result["is_identity_verified"] is True


@patch("leadfinder.services.ai.reconcile_lead.GroqJSONClient.complete_json")
def test_reconcile_and_verify_lead_fallback(mock_complete):
    # GroqJSONClient returning None (simulate API failure)
    mock_complete.return_value = None
    
    gathered_contacts = {
        "public_email": "fallback@janedoe.com",
        "public_phone": "+12065550100",
        "representation_email": "agent@literaryagency.com",
        "publicist_email": None,
    }
    evidence = [
        {
            "evidence_type": "contact_page",
            "field_name": "public_email",
            "field_value": "fallback@janedoe.com",
            "source_url": "https://janedoe.com/contact",
            "source_title": "Jane Doe - Contact",
            "source_snippet": "Email fallback@janedoe.com and call +1 206-555-0100.",
        },
        {
            "evidence_type": "contact_page",
            "field_name": "public_phone",
            "field_value": "+12065550100",
            "source_url": "https://janedoe.com/contact",
            "source_title": "Jane Doe - Contact",
            "source_snippet": "Email fallback@janedoe.com and call +1 206-555-0100.",
        },
        {
            "evidence_type": "publisher_site",
            "field_name": "representation_email",
            "field_value": "agent@literaryagency.com",
            "source_url": "https://literaryagency.com/authors/jane-doe",
            "source_title": "Jane Doe representation",
            "source_snippet": "Jane Doe is represented by agent@literaryagency.com.",
        },
    ]
    
    result = reconcile_and_verify_lead(
        author_name="Jane Doe",
        book_title="My First Novel",
        gathered_contacts=gathered_contacts,
        all_evidence=evidence,
        use_ai=True,
    )
    
    assert result["verified_public_email"] == "fallback@janedoe.com"
    assert result["verified_public_phone"] == "+12065550100"
    assert result["verified_representation_email"] == "agent@literaryagency.com"
    assert result["is_identity_verified"] is True
    assert "failed" in result["identity_verification_reason"].lower()
