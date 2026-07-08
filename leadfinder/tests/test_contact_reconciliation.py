from __future__ import annotations

from leadfinder.services.ai.reconcile_lead import reconcile_and_verify_lead


def test_reconcile_fallback_drops_catalog_contacts_when_ai_disabled():
    result = reconcile_and_verify_lead(
        "Step Techniques",
        "Children's Book Illustration: Step",
        {
            "public_email": "openlibrary@archive.org",
            "public_phone": "+16812413766",
            "representation_email": "",
            "publicist_email": "",
        },
        [
            {
                "evidence_type": "contact_page",
                "field_name": "public_email",
                "field_value": "openlibrary@archive.org",
                "source_url": "https://openlibrary.org/about",
                "source_title": "About Open Library",
                "source_snippet": "Contact Open Library.",
            },
            {
                "evidence_type": "contact_page",
                "field_name": "public_phone",
                "field_value": "+16812413766",
                "source_url": "https://openlibrary.org/about",
                "source_title": "About Open Library",
                "source_snippet": "Contact Open Library.",
            },
        ],
        use_ai=False,
    )

    assert result["verified_public_email"] is None
    assert result["verified_public_phone"] is None
    assert result["is_identity_verified"] is False


def test_reconcile_fallback_keeps_author_domain_contact_when_ai_disabled():
    result = reconcile_and_verify_lead(
        "Avery Moon",
        "The Moonlit Bunny Adventure",
        {
            "public_email": "hello@averymoonbooks.com",
            "public_phone": "",
            "representation_email": "",
            "publicist_email": "",
        },
        [
            {
                "evidence_type": "contact_page",
                "field_name": "public_email",
                "field_value": "hello@averymoonbooks.com",
                "source_url": "https://averymoonbooks.com/contact",
                "source_title": "Avery Moon - Contact",
                "source_snippet": "Official contact page for author Avery Moon.",
            }
        ],
        use_ai=False,
    )

    assert result["verified_public_email"] == "hello@averymoonbooks.com"
    assert result["is_identity_verified"] is True

