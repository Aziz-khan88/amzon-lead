"""Recover emails and phones that sites hide from plain-text extraction.

Author sites routinely obfuscate contact details to foil naive scrapers:
Cloudflare ``data-cfemail`` payloads, ``mailto:``/``tel:`` links, ``name [at]
domain [dot] com`` prose, HTML-entity-encoded addresses, and JSON-LD blobs.
``extract_visible_text`` throws all of that away, so the main crawl path used
to miss these values entirely.  This module works on the *raw HTML* and only
returns values that still pass the strict ``contact_regex`` validators.
"""

from __future__ import annotations

import html as html_lib
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup

from leadfinder.services.crawl.contact_regex import extract_emails, extract_phones
from leadfinder.services.pipeline.lead_validator import validate_phone_number


# Requires an explicit at/dot separator so prose like "contact a writer at a
# publisher" can never become a fabricated address.
OBFUSCATED_EMAIL_RE = re.compile(
    r"(?<![\w.+-])"
    r"(?P<local>[A-Z0-9._%+-]+)"
    r"\s*(?:[\[({<]\s*)?(?:at|@)(?:\s*[\])}>])?\s*"
    r"(?P<domain>[A-Z0-9-]+(?:\s*(?:[\[({<]\s*)?dot(?:\s*[\])}>])?\s*[A-Z0-9-]+)+)"
    r"(?![\w-])",
    re.IGNORECASE,
)
AT_STANDARD_DOMAIN_RE = re.compile(
    r"(?<![\w.+-])"
    r"(?P<local>[A-Z0-9._%+-]+)"
    r"\s*(?:[\[({<]\s*)?(?:at)(?:\s*[\])}>])?\s*"
    r"(?P<domain>[A-Z0-9-]+(?:\.[A-Z0-9-]+)+)"
    r"(?![\w-])",
    re.IGNORECASE,
)
# JSON-LD / microdata attributes, e.g. "email": "me@example.com"
JSON_LD_EMAIL_RE = re.compile(r'"(?:email|contactEmail)"\s*:\s*"([^"@\s]+@[^"\s]+)"', re.IGNORECASE)


def decode_cloudflare_hex(value: str) -> str:
    """Decode Cloudflare's documented client-side email obfuscation payload."""

    payload = (value or "").strip()
    if len(payload) < 4 or len(payload) % 2 or not re.fullmatch(r"[0-9a-fA-F]+", payload):
        return ""
    try:
        key = int(payload[:2], 16)
        return "".join(chr(int(payload[index : index + 2], 16) ^ key) for index in range(2, len(payload), 2))
    except ValueError:
        return ""


def _domain_from_obfuscated(raw: str) -> str:
    return re.sub(
        r"\s*(?:[\[({<]\s*)?dot(?:\s*[\])}>])?\s*",
        ".",
        raw,
        flags=re.IGNORECASE,
    )


# English stopwords that appear right before "at" in prose and must never
# become an email local part ("contact me at jane.doe@..." → not "me@...").
_LOCAL_PART_STOPWORDS = {"me", "you", "us", "him", "her", "them", "it", "we", "i"}


def obfuscated_emails_from_text(text: str) -> list[str]:
    """Find ``name [at] domain [dot] com`` style addresses in plain text."""

    emails: list[str] = []
    for pattern in (OBFUSCATED_EMAIL_RE, AT_STANDARD_DOMAIN_RE):
        for match in pattern.finditer(text or ""):
            local = match.group("local")
            if local.lower() in _LOCAL_PART_STOPWORDS:
                continue
            domain = _domain_from_obfuscated(match.group("domain"))
            candidate = f"{local}@{domain}"
            for email in extract_emails(candidate):
                if email not in emails:
                    emails.append(email)
    return emails


def extract_hidden_contacts(html: str) -> tuple[list[str], list[str]]:
    """Extract validated (emails, phones) hidden in raw HTML markup.

    Sources: mailto:/tel: links, Cloudflare data-cfemail payloads and
    /cdn-cgi/l/email-protection# hrefs, JSON-LD email fields, common
    data-* contact attributes, HTML-entity-encoded text, and at/dot prose.
    Every candidate is re-validated through ``contact_regex`` before return.
    """

    if not html:
        return [], []

    emails: list[str] = []
    phones: list[str] = []

    def _add_email(value: str) -> None:
        for email in extract_emails(value):
            if email not in emails:
                emails.append(email)

    def _add_phone(value: str) -> None:
        normalized = validate_phone_number(value)
        if normalized and normalized not in phones:
            phones.append(normalized)

    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(True):
        href = str(tag.get("href") or "")
        if href.lower().startswith("mailto:"):
            _add_email(unquote(href[7:].split("?", 1)[0]))
        if href.lower().startswith("tel:"):
            _add_phone(unquote(href[4:].split("?", 1)[0]))
        cfemail = str(tag.get("data-cfemail") or "")
        if not cfemail and "/cdn-cgi/l/email-protection#" in href:
            cfemail = href.split("#", 1)[1]
        if cfemail:
            _add_email(decode_cloudflare_hex(cfemail))
        for attribute in ("data-email", "data-contact", "data-phone", "aria-label", "title", "content"):
            value = tag.get(attribute)
            if value:
                value = str(value)
                _add_email(value)
                if attribute in {"data-phone", "data-contact"}:
                    _add_phone(value)

    unescaped = html_lib.unescape(html)
    for match in JSON_LD_EMAIL_RE.finditer(unescaped):
        _add_email(match.group(1))
    for email in obfuscated_emails_from_text(unescaped):
        if email not in emails:
            emails.append(email)
    for phone in extract_phones(unescaped):
        normalized = validate_phone_number(phone)
        if normalized and normalized not in phones:
            phones.append(normalized)

    return emails, phones
