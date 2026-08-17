from __future__ import annotations

from leadfinder.services.amazon.amazon_url_parser import extract_asin, is_amazon_url
from leadfinder.services.eligibility import EligibilityPolicy
from leadfinder.services.pipeline.source_audit import evidence_source_is_trusted_for_contact


VERIFIED_CONTACT_EVIDENCE_TYPES = {
    "contact_page",
    "official_author_site",
    "publisher_site",
    "social_profile",
    "groq_extraction",
    "manual",
}


def has_verified_amazon_book_url(book) -> bool:
    """Require an Amazon marketplace host and a product-path identifier."""
    url = (book.amazon_book_url or "").strip()
    url_asin = extract_asin(url) if is_amazon_url(url) else None
    if not url_asin:
        return False
    stored_asin = (book.asin or "").strip().upper()
    return not stored_asin or stored_asin == url_asin


def contact_field_sources(lead) -> dict[str, bool]:
    fields = ["public_email", "public_phone", "location"]
    return {
        field: (
            lead.evidence.filter(field_name=field, field_value=getattr(lead, field), source_url__gt="").exists()
            if field == "location"
            else has_verified_contact_source(
                lead,
                field,
                getattr(lead, field),
                min_confidence=0.55 if field == "public_phone" else 0.6,
            )
        )
        for field in fields
        if getattr(lead, field)
    }


def has_verified_contact_source(lead, field_name: str, value: str, min_confidence: float = 0.6) -> bool:
    if not value:
        return False
    evidence = lead.evidence.filter(
        field_name=field_name,
        field_value=value,
        source_url__gt="",
        evidence_type__in=VERIFIED_CONTACT_EVIDENCE_TYPES,
        confidence__gte=min_confidence,
    )
    for item in evidence:
        if evidence_source_is_trusted_for_contact(
            author_name=lead.book.author_name,
            book_title=lead.book.title,
            field_name=field_name,
            field_value=value,
            source_url=item.source_url,
            evidence_type=item.evidence_type,
            source_title=item.source_title,
            source_snippet=item.source_snippet,
        ):
            return True

    return False


def has_verified_email_source(lead) -> bool:
    return has_verified_contact_source(lead, "public_email", lead.public_email)


def lead_verification_errors(
    lead,
    require_amazon_url: bool = True,
    require_public_email: bool = True,
    include_social_only_leads: bool = False,
) -> list[str]:
    errors: list[str] = []
    book = lead.book
    author = lead.author_profile

    if require_amazon_url and not has_verified_amazon_book_url(book):
        errors.append("Missing a verified Amazon marketplace book URL.")
    if not book.title or not book.author_name:
        errors.append("Missing title or author.")
    if book.is_childrens_book is False:
        errors.append("Book was classified as not a children's book.")
    if author and author.identity_confidence < 0.65:
        errors.append("Author identity confidence is below verified threshold.")
    if require_public_email and not lead.public_email and not lead.representation_email and not lead.publicist_email:
        errors.append("Missing public email.")
    if lead.public_email and not has_verified_email_source(lead):
        errors.append("Public email is missing a high-confidence author-site/contact-page source.")
    if lead.representation_email and not has_verified_contact_source(lead, "representation_email", lead.representation_email):
        errors.append("Representation email is missing a verified agency/publisher source.")
    if lead.publicist_email and not has_verified_contact_source(lead, "publicist_email", lead.publicist_email):
        errors.append("Publicist email is missing a verified publisher/publicity source.")
    if lead.public_phone and not has_verified_contact_source(lead, "public_phone", lead.public_phone, min_confidence=0.55):
        errors.append("Public phone is missing a verified author-site/contact-page source.")
    has_contact_page = bool(author and author.contact_page_url)
    if (
        not include_social_only_leads
        and not lead.public_email
        and not lead.public_phone
        and not lead.representation_email
        and not lead.publicist_email
        and not has_contact_page
    ):
        errors.append("No direct public email, phone, or contact page.")

    # Call compliance validator
    from leadfinder.services.pipeline.lead_validator import validate_lead_compliance
    compliance_errors = validate_lead_compliance(lead)
    errors.extend(compliance_errors)

    return errors


def can_approve_lead(lead, allow_incomplete_video: bool = False, manual_identity_override: bool = False) -> tuple[bool, list[str]]:
    errors: list[str] = []
    book = lead.book
    author = lead.author_profile
    eligibility = EligibilityPolicy.evaluate(lead)
    if not eligibility.is_verified_ready:
        errors.extend(
            "Lead has no current system-verified contact."
            if code in {
                EligibilityPolicy.REASON_NO_VERIFIED_CONTACT,
                EligibilityPolicy.REASON_IMPORT_AWAITING_VERIFICATION,
            }
            else "Lead is marked do-not-contact."
            for code in eligibility.reason_codes
        )
    if not has_verified_amazon_book_url(book) and not book.evidence.exists():
        errors.append("Lead needs an Amazon URL or strong book source.")
    if not book.author_name:
        errors.append("Lead needs an author name.")
    if not book.title:
        errors.append("Lead needs a book title.")
    has_contact_path = bool(
        lead.public_email
        or lead.public_phone
        or (author and (author.contact_page_url or author.canonical_website or author.instagram_url or author.facebook_url))
    )
    if not has_contact_path:
        errors.append("Lead needs at least one public contact path.")
    for field, has_source in contact_field_sources(lead).items():
        if not has_source:
            errors.append(f"{field} is missing a source URL.")
    if lead.video_status == "not_checked" and not allow_incomplete_video:
        errors.append("Video search is incomplete.")
    if lead.do_not_contact or lead.manual_review_status == "do_not_contact":
        errors.append("Lead is marked do-not-contact.")
    if author and author.identity_confidence < 0.5 and not manual_identity_override:
        errors.append("Author identity is unclear.")
    errors.extend(error for error in lead_verification_errors(lead, require_public_email=False, include_social_only_leads=True) if error not in errors)
    return not errors, errors
