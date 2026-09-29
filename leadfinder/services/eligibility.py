"""One authoritative definition of a lead that is ready for review or delivery.

Verification is a property of a *current contact value*, not of an uploaded
spreadsheet row.  Keeping that distinction here prevents dashboards, filters,
and assignment jobs from drifting into different definitions of "verified".
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Exists, OuterRef, Q, QuerySet

from leadfinder.models import ContactCandidate, Lead


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    """The user-facing result of evaluating a single lead."""

    is_verified_ready: bool
    reason_codes: tuple[str, ...]
    verified_contact_id: object | None = None


class EligibilityPolicy:
    """Central policy for verified-ready lead queues.

    A lead is verified-ready only when it is not suppressed and one of its
    *current* public contact fields has a system-verified ContactCandidate.
    Legacy candidates created by the former manual-import shortcut are
    deliberately excluded: ``manual_import`` was an uploader assertion, not a
    verification check.
    """

    REASON_DO_NOT_CONTACT = "do_not_contact"
    REASON_NO_VERIFIED_CONTACT = "no_current_verified_contact"
    REASON_IMPORT_AWAITING_VERIFICATION = "import_awaiting_verification"

    _CONTACT_FIELDS = {
        "email": ("public_email", "representation_email", "publicist_email"),
        "phone": ("public_phone",),
    }

    @classmethod
    def _verified_current_contact_subquery(cls):
        """Return candidates whose value still matches a field on the outer Lead."""
        email_match = Q(channel="email", normalized_value=OuterRef("public_email"))
        email_match |= Q(channel="email", normalized_value=OuterRef("representation_email"))
        email_match |= Q(channel="email", normalized_value=OuterRef("publicist_email"))
        phone_match = Q(channel="phone", normalized_value=OuterRef("public_phone"))
        return (
            ContactCandidate.objects.filter(
                lead_id=OuterRef("pk"),
                verification_status="verified",
            )
            .exclude(normalized_value="")
            .exclude(deliverability_status="manual_import")
            .filter(email_match | phone_match)
        )

    @classmethod
    def annotate(cls, queryset: QuerySet | None = None) -> QuerySet:
        """Annotate a Lead queryset with ``has_verified_current_contact``."""
        queryset = queryset if queryset is not None else Lead.objects.all()
        return queryset.annotate(
            has_verified_current_contact=Exists(cls._verified_current_contact_subquery())
        )

    @classmethod
    def verified_ready(cls, queryset: QuerySet | None = None) -> QuerySet:
        """Return leads safe to describe as verified-ready in the product."""
        return (
            cls.annotate(queryset)
            .filter(do_not_contact=False, has_verified_current_contact=True)
            .exclude(manual_review_status="do_not_contact")
        )

    @classmethod
    def needs_review(cls, queryset: QuerySet | None = None) -> QuerySet:
        """Return unsuppressed, non-failed leads without a verified current contact."""
        return (
            cls.annotate(queryset)
            .filter(do_not_contact=False, has_verified_current_contact=False)
            .exclude(manual_review_status="do_not_contact")
            .exclude(verification_status="not_verified")
        )

    @classmethod
    def _normalised_current_values(cls, lead: Lead, channel: str) -> set[str]:
        values = set()
        for field_name in cls._CONTACT_FIELDS[channel]:
            value = (getattr(lead, field_name, "") or "").strip()
            if not value:
                continue
            values.add(value.lower() if channel == "email" else value)
        return values

    @classmethod
    def verified_current_contact(cls, lead: Lead) -> ContactCandidate | None:
        """Return the strongest verified candidate that still matches this Lead."""
        candidates = lead.contact_candidates.filter(
            verification_status="verified"
        ).exclude(deliverability_status="manual_import")
        for candidate in candidates:
            candidate_value = (candidate.normalized_value or "").strip()
            if candidate.channel == "email":
                candidate_value = candidate_value.lower()
            if candidate_value and candidate_value in cls._normalised_current_values(lead, candidate.channel):
                return candidate
        return None

    @classmethod
    def evaluate(cls, lead: Lead) -> EligibilityDecision:
        """Explain why one lead is or is not verified-ready."""
        reasons: list[str] = []
        if lead.do_not_contact or lead.manual_review_status == "do_not_contact":
            reasons.append(cls.REASON_DO_NOT_CONTACT)

        candidate = cls.verified_current_contact(lead)
        if candidate is None:
            reasons.append(
                cls.REASON_IMPORT_AWAITING_VERIFICATION
                if lead.uploader_attested
                else cls.REASON_NO_VERIFIED_CONTACT
            )

        return EligibilityDecision(
            is_verified_ready=not reasons,
            reason_codes=tuple(reasons),
            verified_contact_id=candidate.id if candidate else None,
        )
