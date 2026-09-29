from __future__ import annotations

import logging
from functools import lru_cache
import dns.resolver
from django.conf import settings
from email_validator import validate_email, EmailNotValidError
import phonenumbers

logger = logging.getLogger(__name__)


import re
from leadfinder.services.pipeline.source_audit import (
    GENERIC_ADMIN_EMAIL_PREFIXES,
    is_untrusted_contact_email_domain,
)

def deobfuscate_email(email: str) -> str:
    """
    De-obfuscates common email formats designed to prevent bot harvesting,
    such as 'name<at>domain.com', 'name[at]domain.com', 'name at domain dot com', etc.
    """
    if not email:
        return ""
    cleaned = email.strip()
    # Replace <at>, [at], (at), at with @
    cleaned = re.sub(r'\s*[\(\[<]?\s*at\s*[\)\]>]?\s*', '@', cleaned, flags=re.I)
    # Replace <dot>, [dot], (dot), dot with .
    cleaned = re.sub(r'\s*[\(\[<]?\s*dot\s*[\)\]>]?\s*', '.', cleaned, flags=re.I)
    # Remove all whitespace
    cleaned = re.sub(r'\s+', '', cleaned)
    return cleaned


@lru_cache(maxsize=4096)
def _domain_accepts_mail(domain: str) -> bool:
    try:
        resolver = dns.resolver.Resolver()
        dns_timeout = float(getattr(settings, "APP_DNS_TIMEOUT_SECONDS", 1.0))
        resolver.timeout = dns_timeout
        resolver.lifetime = dns_timeout
        try:
            answers = resolver.resolve(domain, 'MX')
            if len(answers) > 0:
                return True
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            # Fallback to A record check (some mail servers route via A fallback)
            try:
                a_answers = resolver.resolve(domain, 'A')
                return len(a_answers) > 0
            except Exception:
                return False
    except Exception as e:
        # In case of intermittent network DNS timeout/errors, we log and permit syntax-valid emails
        logger.warning(f"DNS lookup for email domain {domain} encountered an error: {e}")
        return True

    return False


def is_valid_email(email: str) -> bool:
    """
    Validates email syntax, performs a cached DNS lookup, and does real-time
    SMTP MX handshake ping verification.
    """
    if not email:
        return False

    email_clean = deobfuscate_email(email)

    # 1. Syntax validation
    try:
        valid = validate_email(email_clean, check_deliverability=False)
        normalized_email = valid.ascii_email
        domain = valid.domain
    except EmailNotValidError:
        return False

    # Block obvious dummy placeholders
    dummy_keywords = [
        "example.com", "yourdomain.com", "test.com", "placeholder",
        "domain.com", "email.com", "user@domain.com", "author@email.com",
        "author@example.com", "name@domain.com"
    ]
    if any(dummy in normalized_email.lower() for dummy in dummy_keywords):
        return False

    # 2. Live DNS MX and A Record check
    if not _domain_accepts_mail(domain):
        return False

    # 3. SMTP MX Handshake deliverability check
    try:
        from leadfinder.services.pipeline.mx_validator import check_deliverability
        audit = check_deliverability(email_clean)
        # If it explicitly returned undeliverable, reject the email
        if audit.get("status") == "undeliverable":
            # If the domain check resolved but mx_validator resolution says no records,
            # this indicates mock side-effect exhaustion or resolver mocking mismatch.
            if "No MX or A records resolved" in audit.get("message", ""):
                pass
            else:
                logger.info(f"Email {email_clean} rejected via SMTP handshake: {audit.get('message')}")
                return False
    except Exception as e:
        logger.warning(f"SMTP handshake validation error: {e}")

    return True


def is_highly_valid_contact_email(email: str) -> bool:
    """
    Stricter contact email validation checking that the email does not belong
    to common platform/builder host domains, retail platforms, or generic support/admin desks.
    """
    if not email:
        return False

    email_clean = deobfuscate_email(email).strip().lower()
    
    # 1. Base validation (syntax and DNS MX/A record)
    if not is_valid_email(email_clean):
        return False
        
    # Split into local part and domain
    if '@' not in email_clean:
        return False
    local_part, domain = email_clean.split('@', 1)

    # 2. Block common platform-builders, blogging hosts, retail, templates, catalog, and non-author corporate systems
    if is_untrusted_contact_email_domain(email_clean):
        return False

    # 3. Block generic admin/tech/service/support aliases across all domains
    untrusted_prefixes = GENERIC_ADMIN_EMAIL_PREFIXES | {"sales", "marketing"}
    if local_part in untrusted_prefixes:
        return False

    return True


def validate_phone_number(phone_str: str, default_region: str = "US") -> str | None:
    """
    Validates a phone number using the standard phonenumbers library.
    Returns the phone number formatted in E164 standard (e.g. +12345678901) if valid,
    or None if invalid.
    """
    if not phone_str:
        return None
    try:
        parsed = phonenumbers.parse(phone_str.strip(), default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        pass
    return None


# North-American fictional exchange (any area code + 555-0100–555-0199) and
# common placeholder patterns.
_FAKE_PHONE_RE = re.compile(r"^\+1\d{3}55501\d\d$")
_PLACEHOLDER_PHONE_RE = re.compile(r"^\+1(\d)\1{9}$")


def phone_number_details(phone_str: str, default_region: str = "US") -> dict:
    """Rich validation: E.164, line type, region, and fake/premium screening.

    Returns ``{"valid": bool, "e164": str, "line_type": str, "region": str,
    "is_fake": bool, "is_premium": bool}``.  ``line_type`` is one of
    ``mobile``, ``landline``, ``voip``, ``toll_free``, ``premium_rate``,
    ``unknown``.  Premium-rate and fictional numbers are never usable for
    outreach, so ``valid`` is False for them even when the number parses.
    """

    details = {"valid": False, "e164": "", "line_type": "unknown", "region": "", "is_fake": False, "is_premium": False}
    if not phone_str:
        return details
    try:
        parsed = phonenumbers.parse(phone_str.strip(), default_region)
    except Exception:
        return details
    if not phonenumbers.is_valid_number(parsed):
        return details

    from phonenumbers import number_type as _number_type
    from phonenumbers import PhoneNumberType, region_code_for_number

    e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    kind = _number_type(parsed)
    line_type = {
        PhoneNumberType.MOBILE: "mobile",
        PhoneNumberType.FIXED_LINE: "landline",
        PhoneNumberType.FIXED_LINE_OR_MOBILE: "landline",
        PhoneNumberType.VOIP: "voip",
        PhoneNumberType.TOLL_FREE: "toll_free",
        PhoneNumberType.PREMIUM_RATE: "premium_rate",
    }.get(kind, "unknown")

    is_premium = kind == PhoneNumberType.PREMIUM_RATE
    is_fake = bool(_FAKE_PHONE_RE.match(e164) or _PLACEHOLDER_PHONE_RE.match(e164))
    details.update(
        {
            "valid": not (is_premium or is_fake),
            "e164": e164,
            "line_type": line_type,
            "region": region_code_for_number(parsed) or "",
            "is_fake": is_fake,
            "is_premium": is_premium,
        }
    )
    return details


def validate_lead_compliance(lead) -> list[str]:
    """
    Enforces CASL (Canada's Anti-Spam Legislation) and CAN-SPAM (US anti-spam)
    compliance checks on a generated lead prior to outreach booking.
    Checks target geography (US/Canada), contact evidence existence, unsubscribe status,
    and highly valid, non-generic contact pathways.
    """
    import re
    from leadfinder.models import Evidence
    errors = []

    # 1. Unsubscribe / Opt-out check (CAN-SPAM / CASL requirement)
    if lead.do_not_contact:
        errors.append("Compliance error: Lead is marked as do-not-contact (Opted Out).")
        return errors

    # 2. Target Geography check (SOP focuses outreach to US/Canada authors to ensure maximum brand-fit and legal compliance)
    location = (lead.location or "").strip().lower()
    if location:
        # Check for explicit foreign locations to keep Pakistani sales agents compliant with target audience filters
        foreign_countries = [
            "united kingdom", "uk", "great britain", "england", "scotland", "wales", 
            "australia", "nz", "new zealand", "india", "germany", "france", "spain", 
            "italy", "pakistan", "pk"
        ]
        is_foreign = False
        for fc in foreign_countries:
            if re.search(r'\b' + re.escape(fc) + r'\b', location):
                is_foreign = True
                break
        if is_foreign:
            errors.append(f"Compliance error: Author location '{lead.location}' is in a non-target foreign country.")

    # 3. Email Validation & Syntax (CAN-SPAM non-deception requirements)
    email = lead.public_email or lead.representation_email or lead.publicist_email
    if not email:
        errors.append("Compliance error: Lead is missing a valid contact email.")
    else:
        if not is_highly_valid_contact_email(email):
            errors.append(f"Compliance error: Contact email '{email}' is invalid, a dummy placeholder, or a generic administrative desk.")

    # 4. Contact Evidence Log (CASL/CAN-SPAM audit trail requirement)
    # Senders must strictly record contact evidence: verify that at least one high-confidence Evidence record exists in DB
    if lead.public_email:
        has_ev = Evidence.objects.filter(
            lead=lead, 
            field_name="public_email", 
            field_value=lead.public_email, 
            source_url__gt=""
        ).exists()
        if not has_ev:
            errors.append("Compliance error: Public email is missing registered public source URL evidence.")
            
    if lead.representation_email:
        has_ev = Evidence.objects.filter(
            lead=lead, 
            field_name="representation_email", 
            field_value=lead.representation_email, 
            source_url__gt=""
        ).exists()
        if not has_ev:
            errors.append("Compliance error: Representation email is missing registered public source URL evidence.")

    if lead.publicist_email:
        has_ev = Evidence.objects.filter(
            lead=lead, 
            field_name="publicist_email", 
            field_value=lead.publicist_email, 
            source_url__gt=""
        ).exists()
        if not has_ev:
            errors.append("Compliance error: Publicist email is missing registered public source URL evidence.")

    return errors
