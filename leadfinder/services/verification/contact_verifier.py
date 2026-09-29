from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from email_validator import EmailNotValidError, validate_email

from leadfinder.models import ContactCandidate, Evidence, VerificationBatch, VerificationCheck
from leadfinder.services.pipeline.lead_validator import validate_phone_number
from leadfinder.services.pipeline.mx_validator import check_deliverability
from leadfinder.services.pipeline.source_audit import (
    evidence_source_is_trusted_for_contact,
    is_untrusted_contact_email_domain,
    registered_domain_from_email,
    registered_domain_from_url,
)


VERIFICATION_VERSION = "contact-v1"
CONTACT_FIELDS = {
    "public_email": ("email", "author"),
    "representation_email": ("email", "agent"),
    "publicist_email": ("email", "publicist"),
    "public_phone": ("phone", "author"),
}
ROLE_PRIORITY = {"author": 5, "author_business": 4, "agent": 3, "publicist": 2, "unknown": 1}
CHANNEL_PRIORITY = {"email": 2, "phone": 1}
STATUS_PRIORITY = {"verified": 3, "other": 2, "not_verified": 1}

# Evidence types recorded from pages the author (or their team) controls.
AUTHOR_OWNED_EVIDENCE_TYPES = {"official_author_site", "contact_page", "manual"}


def evidence_type_looks_author_owned(item) -> bool:
    return item.evidence_type in AUTHOR_OWNED_EVIDENCE_TYPES


@dataclass(slots=True)
class CheckResult:
    check_type: str
    result: str
    score_delta: int = 0
    reason_code: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def _normalize_email(value: str) -> tuple[str, bool]:
    try:
        result = validate_email((value or "").strip(), check_deliverability=False)
    except EmailNotValidError:
        return (value or "").strip().lower(), False
    return (result.normalized.lower(), True)


def _normalize_contact(channel: str, value: str) -> tuple[str, bool]:
    if channel == "email":
        return _normalize_email(value)
    normalized = validate_phone_number(value)
    return (normalized or (value or "").strip(), bool(normalized))


def _candidate_inputs(lead, evidence_items: list[Evidence] | None = None) -> list[tuple[str, str, str, str]]:
    values: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for field_name, (channel, role) in CONTACT_FIELDS.items():
        value = getattr(lead, field_name, "") or ""
        if value:
            normalized, _ = _normalize_contact(channel, value)
            key = (channel, normalized)
            if key not in seen:
                seen.add(key)
                values.append((field_name, channel, role, value))
    items = evidence_items if evidence_items is not None else lead.evidence.filter(field_name__in=CONTACT_FIELDS).exclude(field_value="")
    for item in items:
        if item.field_name not in CONTACT_FIELDS or not item.field_value:
            continue
        channel, role = CONTACT_FIELDS[item.field_name]
        normalized, _ = _normalize_contact(channel, item.field_value)
        key = (channel, normalized)
        if normalized and key not in seen:
            seen.add(key)
            values.append((item.field_name, channel, role, item.field_value))
    return values


def _matching_evidence(lead, field_name: str, value: str, normalized: str, channel: str, evidence_items: list[Evidence] | None = None):
    items = evidence_items if evidence_items is not None else lead.evidence.filter(field_name=field_name).exclude(source_url="")
    matches = []
    for item in items:
        if item.field_name != field_name or not item.source_url:
            continue
        item_normalized, _ = _normalize_contact(channel, item.field_value)
        if item.field_value == value or item_normalized == normalized:
            matches.append(item)
    return matches


def _trusted_sources(lead, field_name: str, normalized: str, evidence: list[Evidence]) -> list[Evidence]:
    trusted = []
    for item in evidence:
        if evidence_source_is_trusted_for_contact(
            author_name=lead.book.author_name,
            book_title=lead.book.title,
            field_name=field_name,
            field_value=normalized,
            source_url=item.source_url,
            evidence_type=item.evidence_type,
            source_title=item.source_title,
            source_snippet=item.source_snippet,
        ):
            trusted.append(item)
    return trusted


def _email_checks(lead, field_name: str, normalized: str, syntax_valid: bool, evidence: list[Evidence], check_network: bool):
    checks: list[CheckResult] = []
    blocked = bool(syntax_valid and is_untrusted_contact_email_domain(normalized))
    checks.append(CheckResult("syntax", "pass" if syntax_valid else "fail", 15 if syntax_valid else 0, "valid_syntax" if syntax_valid else "invalid_syntax"))
    checks.append(CheckResult("source_policy", "fail" if blocked else "pass", 0, "blocked_email_domain" if blocked else "allowed_email_domain"))

    trusted = _trusted_sources(lead, field_name, normalized, evidence) if syntax_valid and not blocked else []
    source_ok = bool(trusted)
    checks.append(CheckResult("trusted_source", "pass" if source_ok else "unknown", 30 if source_ok else 0, "trusted_exact_source" if source_ok else "missing_trusted_source", {"source_urls": [item.source_url for item in trusted]}))

    identity_ok = bool(source_ok and lead.author_profile and lead.author_profile.identity_confidence >= 0.65)
    checks.append(CheckResult("identity_match", "pass" if identity_ok else "unknown", 30 if identity_ok else 0, "identity_aligned" if identity_ok else "identity_inconclusive", {"identity_confidence": lead.author_profile.identity_confidence if lead.author_profile else 0}))
    checks.append(CheckResult("role_match", "pass", 10, f"role_{CONTACT_FIELDS[field_name][1]}"))

    # Domain alignment: an email living on the author's own verified website
    # domain (author@authorname.com found on authorname.com) is the strongest
    # ownership signal available and is what lifts a candidate to 100/100.
    author_domains = set()
    if lead.author_profile:
        for url in (lead.author_profile.canonical_website, lead.author_profile.contact_page_url):
            domain = registered_domain_from_url(url or "")
            if domain:
                author_domains.add(domain)
    for item in trusted:
        domain = registered_domain_from_url(item.source_url)
        if domain and evidence_type_looks_author_owned(item):
            author_domains.add(domain)
    email_domain = registered_domain_from_email(normalized)
    domain_aligned = bool(email_domain and email_domain in author_domains)
    checks.append(
        CheckResult(
            "domain_alignment",
            "pass" if domain_aligned else "unknown",
            10 if domain_aligned else 0,
            "email_on_author_domain" if domain_aligned else "email_domain_not_author_owned",
            {"email_domain": email_domain, "author_domains": sorted(author_domains)},
        )
    )

    # SMTP RCPT-TO probing (port 25) is blocked on most hosts, so deliverability
    # is a confidence bonus — never a hard gate.  A definitive "undeliverable"
    # or a catch-all domain still blocks verification; "unknown" does not.
    # When a hosted verification API key is configured (Hunter/ZeroBounce/
    # NeverBounce) its verdict is used first; SMTP is the fallback.
    deliverability = {"status": "unknown", "message": "Network verification was not requested."}
    if syntax_valid and not blocked and check_network:
        from leadfinder.services.verification.api_verifier import api_verify_email

        deliverability = api_verify_email(normalized) or check_deliverability(normalized)
    delivery_status = str(deliverability.get("status") or "unknown")
    if delivery_status == "deliverable":
        delivery_result, delivery_points = "pass", 15
    elif delivery_status in {"undeliverable", "catch_all"}:
        delivery_result, delivery_points = ("fail", 0) if delivery_status == "undeliverable" else ("unknown", 0)
    else:
        delivery_result, delivery_points = "unknown", 0
    checks.append(CheckResult("deliverability", delivery_result, delivery_points, f"smtp_{delivery_status}" if "provider" not in deliverability else f"api_{deliverability['provider']}_{delivery_status}", deliverability))

    # Shared-channel detection: the same address appearing on many unrelated
    # leads is usually an agency/publicist desk, not the author.  It stays
    # usable (agent channels are legitimate) but is flagged and loses the
    # corroboration bonus so one shared address cannot self-corroborate.
    from leadfinder.services.pipeline.shared_contacts import count_leads_sharing_contact

    shared_count = count_leads_sharing_contact("email", normalized, exclude_lead_id=lead.id)
    shared_threshold = int(getattr(settings, "APP_SHARED_CONTACT_THRESHOLD", 3))
    is_shared_channel = shared_count >= shared_threshold
    checks.append(
        CheckResult(
            "shared_channel",
            "unknown" if is_shared_channel else "pass",
            0,
            f"shared_across_{shared_count}_leads" if is_shared_channel else "unique_to_lead",
            {"shared_lead_count": shared_count},
        )
    )

    domains = {registered_domain_from_url(item.source_url) for item in trusted if registered_domain_from_url(item.source_url)}
    corroborated = len(domains) >= 2 and not is_shared_channel
    checks.append(CheckResult("corroboration", "pass" if corroborated else "unknown", 15 if corroborated else 0, "multiple_independent_sources" if corroborated else "single_source"))

    score = min(100, sum(item.score_delta for item in checks))
    explicit_failure = not syntax_valid or blocked or delivery_status == "undeliverable"
    hard_gates = (
        syntax_valid
        and not blocked
        and source_ok
        and identity_ok
        and delivery_status in {"deliverable", "unknown"}
    )
    status = "verified" if hard_gates and score >= 85 else ("not_verified" if explicit_failure else "other")
    return status, score, delivery_status, checks


def _phone_checks(lead, field_name: str, normalized: str, valid: bool, evidence: list[Evidence]):
    from leadfinder.services.pipeline.lead_validator import phone_number_details

    phone_details = phone_number_details(normalized)
    blocked_phone = phone_details["is_fake"] or phone_details["is_premium"]
    effective_valid = valid and not blocked_phone
    checks = [
        CheckResult("phone_validity", "pass" if effective_valid else "fail", 15 if effective_valid else 0, "valid_e164" if effective_valid else "invalid_phone"),
        CheckResult(
            "phone_line_type",
            "fail" if blocked_phone else "pass",
            0,
            "premium_or_fake_number" if blocked_phone else f"line_{phone_details['line_type']}",
            {key: phone_details[key] for key in ("line_type", "region", "is_fake", "is_premium")},
        ),
    ]
    trusted = _trusted_sources(lead, field_name, normalized, evidence) if effective_valid else []
    source_ok = bool(trusted)
    checks.append(CheckResult("trusted_source", "pass" if source_ok else "unknown", 30 if source_ok else 0, "trusted_exact_source" if source_ok else "missing_trusted_source", {"source_urls": [item.source_url for item in trusted]}))
    identity_ok = bool(source_ok and lead.author_profile and lead.author_profile.identity_confidence >= 0.65)
    checks.append(CheckResult("identity_match", "pass" if identity_ok else "unknown", 35 if identity_ok else 0, "identity_aligned" if identity_ok else "identity_inconclusive"))
    checks.append(CheckResult("role_match", "pass", 10, f"role_{CONTACT_FIELDS[field_name][1]}"))
    domains = {registered_domain_from_url(item.source_url) for item in trusted if registered_domain_from_url(item.source_url)}
    corroborated = len(domains) >= 2
    checks.append(CheckResult("corroboration", "pass" if corroborated else "unknown", 10 if corroborated else 0, "multiple_independent_sources" if corroborated else "single_source"))
    score = min(100, sum(item.score_delta for item in checks))
    status = "verified" if effective_valid and source_ok and identity_ok and score >= 90 else ("not_verified" if not effective_valid else "other")
    return status, score, "not_applicable", checks


def _selection_key(candidate: ContactCandidate):
    return (
        STATUS_PRIORITY[candidate.verification_status],
        candidate.verification_score,
        CHANNEL_PRIORITY[candidate.channel],
        ROLE_PRIORITY[candidate.role],
        candidate.normalized_value,
    )


@transaction.atomic
def verify_lead_contacts(lead, *, batch: VerificationBatch | None = None, check_network: bool = True):
    """Verify every contact candidate and select exactly one deterministic primary contact."""
    now = timezone.now()
    evaluated: list[ContactCandidate] = []
    # One prefetched evidence list serves candidate collection, matching, and
    # trust screening — previously each helper re-queried per candidate.
    evidence_items = list(lead.evidence.all())
    for field_name, channel, role, raw_value in _candidate_inputs(lead, evidence_items):
        normalized, structurally_valid = _normalize_contact(channel, raw_value)
        if not normalized:
            continue
        candidate, _ = ContactCandidate.objects.update_or_create(
            lead=lead,
            channel=channel,
            normalized_value=normalized,
            defaults={"raw_value": raw_value, "role": role, "last_checked_at": now},
        )
        evidence = _matching_evidence(lead, field_name, raw_value, normalized, channel, evidence_items)
        for item in evidence:
            if item.contact_candidate_id != candidate.id:
                item.contact_candidate = candidate
                item.save(update_fields=["contact_candidate"])
        if channel == "email":
            status, score, delivery_status, checks = _email_checks(
                lead, field_name, normalized, structurally_valid, evidence, check_network
            )
        else:
            status, score, delivery_status, checks = _phone_checks(
                lead, field_name, normalized, structurally_valid, evidence
            )
        candidate.verification_status = status
        candidate.verification_score = score
        candidate.deliverability_status = delivery_status
        candidate.selected_reason = "; ".join(check.reason_code for check in checks if check.result != "pass") or "All required verification checks passed."
        candidate.last_checked_at = now
        candidate.save(update_fields=["raw_value", "role", "verification_status", "verification_score", "deliverability_status", "selected_reason", "last_checked_at", "updated_at"])
        VerificationCheck.objects.bulk_create(
            [
                VerificationCheck(
                    candidate=candidate,
                    batch=batch,
                    check_type=check.check_type,
                    result=check.result,
                    score_delta=check.score_delta,
                    reason_code=check.reason_code,
                    details_json=check.details,
                    checker_version=VERIFICATION_VERSION,
                    checked_at=now,
                )
                for check in checks
            ]
        )
        evaluated.append(candidate)

    ContactCandidate.objects.filter(lead=lead, is_primary=True).update(is_primary=False)
    primary = max(evaluated, key=_selection_key) if evaluated else None
    if primary:
        primary.is_primary = True
        primary.save(update_fields=["is_primary", "updated_at"])
        status = "verified" if any(item.verification_status == "verified" for item in evaluated) else (
            "not_verified" if all(item.verification_status == "not_verified" for item in evaluated) else "other"
        )
        if status == "verified" and primary.verification_status != "verified":
            primary = max((item for item in evaluated if item.verification_status == "verified"), key=_selection_key)
            ContactCandidate.objects.filter(lead=lead).update(is_primary=False)
            primary.is_primary = True
            primary.save(update_fields=["is_primary", "updated_at"])
        reason = primary.selected_reason
        score = primary.verification_score
    else:
        status, score, reason = "other", 0, "No public email or phone candidate was found."

    lead.primary_contact = primary
    lead.verification_status = status
    lead.verification_score = score
    lead.verification_reason = reason
    lead.verification_reasons_json = [
        {"candidate": item.normalized_value, "status": item.verification_status, "score": item.verification_score, "reason": item.selected_reason}
        for item in sorted(evaluated, key=_selection_key, reverse=True)
    ]
    lead.verification_version = VERIFICATION_VERSION
    lead.verified_at = now if status == "verified" else None
    selected_contact_field = None
    if primary and primary.verification_status == "verified":
        if primary.channel == "phone":
            selected_contact_field = "public_phone"
        elif primary.role == "agent":
            selected_contact_field = "representation_email"
        elif primary.role == "publicist":
            selected_contact_field = "publicist_email"
        else:
            selected_contact_field = "public_email"
        setattr(lead, selected_contact_field, primary.normalized_value)
    update_fields = [
        "primary_contact",
        "verification_status",
        "verification_score",
        "verification_reason",
        "verification_reasons_json",
        "verification_version",
        "verified_at",
        "updated_at",
    ]
    if selected_contact_field:
        update_fields.append(selected_contact_field)
    lead.save(update_fields=update_fields)
    return lead
