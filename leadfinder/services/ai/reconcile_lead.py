from __future__ import annotations

import re
from typing import Any
from .groq_client import GroqJSONClient
from leadfinder.services.pipeline.source_audit import evidence_source_is_trusted_for_contact


def _digits(value: str) -> str:
    return re.sub(r"\D+", "", value or "")


def _value_appears_in_evidence(value: str, evidence: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(evidence.get(key) or "")
        for key in ["field_value", "source_url", "source_title", "source_snippet", "snippet"]
    ).lower()
    if not value:
        return False
    if value.lower() in haystack:
        return True
    digits = _digits(value)
    return bool(digits and digits in _digits(haystack))


def _has_trusted_evidence(
    *,
    author_name: str,
    book_title: str,
    field_name: str,
    field_value: str | None,
    all_evidence: list[dict[str, Any]],
) -> bool:
    if not field_value:
        return False
    for item in all_evidence:
        if not _value_appears_in_evidence(str(field_value), item):
            continue
        if evidence_source_is_trusted_for_contact(
            author_name=author_name,
            book_title=book_title,
            field_name=field_name,
            field_value=str(field_value),
            source_url=item.get("source_url", ""),
            evidence_type=item.get("evidence_type") or item.get("type", ""),
            source_title=item.get("source_title", ""),
            source_snippet=item.get("source_snippet") or item.get("snippet", ""),
        ):
            return True
    return False


def _trusted_or_none(author_name: str, book_title: str, field_name: str, value: Any, all_evidence: list[dict[str, Any]]):
    if not value:
        return None
    return value if _has_trusted_evidence(
        author_name=author_name,
        book_title=book_title,
        field_name=field_name,
        field_value=str(value),
        all_evidence=all_evidence,
    ) else None


def reconcile_and_verify_lead(
    author_name: str,
    book_title: str,
    gathered_contacts: dict[str, Any],
    all_evidence: list[dict[str, Any]],
    use_ai: bool = True,
) -> dict[str, Any]:
    """
    Rigorously audit and reconcile all crawled evidence and extracted contacts using AI.
    Verifies if the contact info genuinely belongs to the real author (not a generic entity or platform),
    fixes/heals any missing contacts found in the evidence logs, and returns the verified outputs.
    """
    if not use_ai:
        # Pass through when AI is disabled
        verified_public_email = _trusted_or_none(author_name, book_title, "public_email", gathered_contacts.get("public_email"), all_evidence)
        verified_public_phone = _trusted_or_none(author_name, book_title, "public_phone", gathered_contacts.get("public_phone"), all_evidence)
        verified_representation_email = _trusted_or_none(
            author_name, book_title, "representation_email", gathered_contacts.get("representation_email"), all_evidence
        )
        verified_publicist_email = _trusted_or_none(
            author_name, book_title, "publicist_email", gathered_contacts.get("publicist_email"), all_evidence
        )
        return {
            "verified_public_email": verified_public_email,
            "verified_public_phone": verified_public_phone,
            "verified_representation_email": verified_representation_email,
            "verified_publicist_email": verified_publicist_email,
            "is_identity_verified": bool(verified_public_email or verified_representation_email or verified_publicist_email),
            "identity_verification_score": 0.7 if (verified_public_email or verified_representation_email or verified_publicist_email) else 0.3,
            "identity_verification_reason": "Pass-through mode (AI review disabled). Please review manually.",
            "reconciliation_fixes": [],
        }

    from leadfinder.services.pipeline.lead_validator import is_highly_valid_contact_email, validate_phone_number

    # Compile a clean list of evidence snippets to send to the AI
    evidence_payload = []
    for item in all_evidence:
        evidence_payload.append({
            "type": item.get("evidence_type", "search_result"),
            "field": item.get("field_name", ""),
            "value": item.get("field_value", ""),
            "source_url": item.get("source_url", ""),
            "snippet": item.get("source_snippet", "")[:300],
        })

    payload = {
        "author_name": author_name,
        "book_title": book_title,
        "gathered_contacts": gathered_contacts,
        "all_crawled_evidence": evidence_payload,
    }

    prompt = (
        "You are the Lead Reconciler and Senior Verification Auditor.\n"
        "Your goal is to perform a deep identity verification on the extracted contacts and all gathered search/crawl evidence.\n\n"
        "CRITICAL INSTRUCTIONS:\n"
        "1. IDENTITY VALIDITY: Check if the email, phone, and socials belong to the actual real person (the author/illustrator) and match the book's context. Assess this explicitly.\n"
        "2. DATA HEALING/RECONCILIATION: Review all 'all_crawled_evidence' entries. If a valid author contact email or phone was mentioned in any snippet, URL, or crawled page but was left out or set to null in 'gathered_contacts', extract it to heal the lead!\n"
        "3. DISCREPANCY RESOLUTION: If there are conflicting contacts, determine which one is the correct, highly verified personal or business contact for the author, and reject platforms or corporate domains.\n"
        "4. RIGOROUS OUTCOME CHECKS:\n"
        "   - verified_public_email: Direct email for the author (e.g. hello@authorsite.com, authorname@gmail.com). Must be highly valid.\n"
        "   - verified_public_phone: Standard public phone number for the author.\n"
        "   - verified_representation_email: Literary agent / agency rights contact.\n"
        "   - verified_publicist_email: Publicity, PR, or booking desk email.\n"
        "   - is_identity_verified: boolean. Set to true ONLY if you are absolutely confident the email/phone belongs to the target author or their literary agent (identity match score >= 0.7).\n"
        "   - identity_verification_score: float (0.0 to 1.0) assessing confidence that this contact info represents the real author.\n"
        "   - identity_verification_reason: A precise explanation of how you verified the identity or why you have doubts.\n"
        "   - reconciliation_fixes: Array of strings listing exactly what was corrected or healed (e.g., 'Healed public_email from snippet', 'Confirmed email matches domain of official site', 'Rejected support@wordpress.com as generic platform alias').\n\n"
        "Ensure your JSON response contains exactly these fields and types:\n"
        "- verified_public_email: string or null\n"
        "- verified_public_phone: string or null\n"
        "- verified_representation_email: string or null\n"
        "- verified_publicist_email: string or null\n"
        "- is_identity_verified: boolean\n"
        "- identity_verification_score: float\n"
        "- identity_verification_reason: string\n"
        "- reconciliation_fixes: array of strings"
    )

    ai = GroqJSONClient().complete_json(prompt, payload)
    if not ai:
        # Fallback on Groq error/failure
        verified_public_email = _trusted_or_none(author_name, book_title, "public_email", gathered_contacts.get("public_email"), all_evidence)
        verified_public_phone = _trusted_or_none(author_name, book_title, "public_phone", gathered_contacts.get("public_phone"), all_evidence)
        verified_representation_email = _trusted_or_none(
            author_name, book_title, "representation_email", gathered_contacts.get("representation_email"), all_evidence
        )
        verified_publicist_email = _trusted_or_none(
            author_name, book_title, "publicist_email", gathered_contacts.get("publicist_email"), all_evidence
        )
        return {
            "verified_public_email": verified_public_email,
            "verified_public_phone": verified_public_phone,
            "verified_representation_email": verified_representation_email,
            "verified_publicist_email": verified_publicist_email,
            "is_identity_verified": bool(verified_public_email or verified_representation_email or verified_publicist_email),
            "identity_verification_score": 0.5 if (verified_public_email or verified_representation_email or verified_publicist_email) else 0.1,
            "identity_verification_reason": "AI reconciliation failed or timed out. Reverted to standard extraction.",
            "reconciliation_fixes": ["AI failure fallback applied"],
        }

    # Apply strict domain and programmatic validation checks on the final healed values
    final_email = ai.get("verified_public_email")
    final_rep_email = ai.get("verified_representation_email")
    final_publ_email = ai.get("verified_publicist_email")
    final_phone = ai.get("verified_public_phone")

    final_phone = validate_phone_number(final_phone) if final_phone else None
    verified_public_email = (
        final_email
        if final_email
        and is_highly_valid_contact_email(final_email)
        and _has_trusted_evidence(
            author_name=author_name,
            book_title=book_title,
            field_name="public_email",
            field_value=final_email,
            all_evidence=all_evidence,
        )
        else None
    )
    verified_public_phone = (
        final_phone
        if final_phone
        and _has_trusted_evidence(
            author_name=author_name,
            book_title=book_title,
            field_name="public_phone",
            field_value=final_phone,
            all_evidence=all_evidence,
        )
        else None
    )
    verified_representation_email = (
        final_rep_email
        if final_rep_email
        and is_highly_valid_contact_email(final_rep_email)
        and _has_trusted_evidence(
            author_name=author_name,
            book_title=book_title,
            field_name="representation_email",
            field_value=final_rep_email,
            all_evidence=all_evidence,
        )
        else None
    )
    verified_publicist_email = (
        final_publ_email
        if final_publ_email
        and is_highly_valid_contact_email(final_publ_email)
        and _has_trusted_evidence(
            author_name=author_name,
            book_title=book_title,
            field_name="publicist_email",
            field_value=final_publ_email,
            all_evidence=all_evidence,
        )
        else None
    )

    return {
        "verified_public_email": verified_public_email,
        "verified_public_phone": verified_public_phone,
        "verified_representation_email": verified_representation_email,
        "verified_publicist_email": verified_publicist_email,
        "is_identity_verified": bool(ai.get("is_identity_verified")),
        "identity_verification_score": float(ai.get("identity_verification_score") or 0.0),
        "identity_verification_reason": str(ai.get("identity_verification_reason") or ""),
        "reconciliation_fixes": list(ai.get("reconciliation_fixes") or []),
    }
