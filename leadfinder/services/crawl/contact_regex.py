from __future__ import annotations

import re

import phonenumbers
from email_validator import EmailNotValidError, validate_email

from leadfinder.services.pipeline.source_audit import BLOCKED_CONTACT_EMAIL_DOMAINS


EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w-])", re.I)
SCRIPT_HINTS = {"example.com", "domain.com", "email.com", "sentry", "wixpress", "schema.org"}
PHONE_CONTEXT_RE = re.compile(r"(contact|call|phone|tel|booking|publicity|media|school visit|speaking)", re.I)

BLACKLISTED_EMAIL_DOMAINS = {
    "archive.org",
    "openlibrary.org",
    "goodreads.com",
    "amazon.com",
    "amazon.co.uk",
    "amazon.ca",
    "mit.edu",
    "mitpressbookstore.mit.edu",
    "target.com",
    "walmart.com",
    "ebay.com",
    "etsy.com",
    "scholastic.com",
    "wordpress.com",
    "wix.com",
    "wixsite.com",
    "blogspot.com",
    "blogger.com",
    "weebly.com",
    "squarespace.com",
    "shopify.com",
    "librarything.com",
    "worldcat.org",
    "loc.gov",
    "fantasticfiction.com",
    "fantasticfiction.co.uk",
    "bookbub.com",
    "litcharts.com",
    "sparknotes.com",
    "harvard.edu",
    "yale.edu",
    "stanford.edu",
} | BLOCKED_CONTACT_EMAIL_DOMAINS

ISBN_CONTEXT_RE = re.compile(
    r"\b(isbn|isbn-?13|isbn-?10|asin|barcode|pages|page\s+count|dimensions|weight|paperback|hardcover|edition|publisher|publication|price|checkout|catalog|qty|quantity)\b",
    re.I
)


def is_valid_isbn10(s: str) -> bool:
    """Mathematically validates if a 10-character string is a valid ISBN-10."""
    if len(s) != 10:
        return False
    total = 0
    for i in range(9):
        if not s[i].isdigit():
            return False
        total += int(s[i]) * (10 - i)
    last = s[9]
    if last in ("X", "x"):
        total += 10
    elif last.isdigit():
        total += int(last)
    else:
        return False
    return total % 11 == 0


def extract_emails(text: str) -> list[str]:
    emails: list[str] = []
    for match in EMAIL_RE.finditer(text or ""):
        email = match.group(1).strip(".,;:()[]{}<>").lower()
        if any(hint in email for hint in SCRIPT_HINTS):
            continue
        
        # Filter against strict blacklist of catalog, retail, and template platforms
        if "@" in email:
            _, domain = email.split("@", 1)
            is_blacklisted = False
            for bl_dom in BLACKLISTED_EMAIL_DOMAINS:
                if domain == bl_dom or domain.endswith("." + bl_dom):
                    is_blacklisted = True
                    break
            if is_blacklisted:
                continue

        window = (text[max(0, match.start() - 120) : match.end() + 120] or "").lower()
        if any(token in window for token in ["function", "var ", "const ", "schema", "sentry", "javascript"]):
            continue
        try:
            validated = validate_email(email, check_deliverability=False)
        except EmailNotValidError:
            continue
        normalized = validated.normalized.lower()
        if normalized not in emails:
            emails.append(normalized)
    return emails


def extract_phones(text: str, region: str = "US", require_context: bool = True) -> list[str]:
    phones: list[str] = []
    if not text:
        return phones
    for match in phonenumbers.PhoneNumberMatcher(text, region):
        # 1. Clean raw matched sequence of formatting to evaluate ISBN characteristics
        raw_clean = re.sub(r"[^\dxX]", "", match.raw_string)
        
        # Suppress ISBN-13 sequences starting with 978/979
        if len(raw_clean) == 13 and raw_clean.startswith(("978", "979")):
            continue
            
        # Suppress valid mathematical ISBN-10 matches
        if len(raw_clean) == 10 and is_valid_isbn10(raw_clean):
            continue

        # 2. Check immediate left and right context (40 characters) for book metadata keywords,
        # but respect sentence boundaries (periods, question marks, exclamations, semicolons, and newlines)
        # to ensure that labels in separate sentences do not falsely suppress this candidate.
        left_context = text[max(0, match.start - 40) : match.start]
        right_context = text[match.end : match.end + 40]
        
        left_clean = re.split(r"[\.\!\?\n\;]", left_context)[-1]
        right_clean = re.split(r"[\.\!\?\n\;]", right_context)[0]
        
        if ISBN_CONTEXT_RE.search(left_clean) or ISBN_CONTEXT_RE.search(right_clean):
            continue

        # 3. Check wider context for required telephone indicators
        window = text[max(0, match.start - 120) : match.end + 120]
        if require_context and not PHONE_CONTEXT_RE.search(window):
            continue
            
        formatted = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
        if formatted not in phones:
            phones.append(formatted)
    return phones
