"""Bounded, public-only contact extraction for author bio links.

This module deliberately handles only pages that are publicly available and
permitted by ``robots.txt``.  It is intended for the one-hop Linktree,
Substack, Carrd, and author-site links that an already identity-matched author
profile exposes; it is not a general-purpose social-media scraper.
"""

from __future__ import annotations

import html as html_lib
import re
import time
from dataclasses import dataclass
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup
from django.conf import settings

from leadfinder.services.crawl.contact_regex import extract_emails, extract_phones
from leadfinder.services.crawl.extract_links import extract_links
from leadfinder.services.crawl.extract_text import extract_meta_description, extract_page_title, extract_visible_text
from leadfinder.services.crawl.robots import can_fetch_url
from leadfinder.services.pipeline.lead_validator import validate_phone_number
from leadfinder.utils.url_safety import is_safe_public_url


SOCIAL_CONTACT_USER_AGENT = "BookTrailerLeadFinder/1.0 (+public bio-link verification; respects robots.txt)"
MAX_SOCIAL_CONTACT_BYTES = 2_000_000
MAX_SOCIAL_CONTACT_REDIRECTS = 3

# These patterns intentionally require an explicit ``at``/``dot`` separator.
# That prevents prose such as "contact a writer at a publisher" from becoming
# a fabricated address.
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


@dataclass(frozen=True, slots=True)
class PublicHtmlPage:
    """A successfully fetched public HTML page."""

    url: str
    html: str
    title: str
    text: str
    links: list[str]


@dataclass(frozen=True, slots=True)
class SocialContactPage:
    """Contacts and provenance extracted from one public bio-link page."""

    url: str
    title: str
    text: str
    links: list[str]
    emails: list[str]
    phones: list[str]


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


def _obfuscated_emails(values: list[str]) -> list[str]:
    emails: list[str] = []
    for value in values:
        for pattern in (OBFUSCATED_EMAIL_RE, AT_STANDARD_DOMAIN_RE):
            for match in pattern.finditer(value):
                domain = re.sub(
                    r"\s*(?:[\[({<]\s*)?dot(?:\s*[\])}>])?\s*",
                    ".",
                    match.group("domain"),
                    flags=re.IGNORECASE,
                )
                candidate = f"{match.group('local')}@{domain}"
                for email in extract_emails(candidate):
                    if email not in emails:
                        emails.append(email)
    return emails


def _contact_values(html: str) -> tuple[list[str], list[str], list[str]]:
    """Collect visible text plus public contact-bearing attributes."""

    soup = BeautifulSoup(html or "", "lxml")
    text = extract_visible_text(html)
    values = [text, html_lib.unescape(html or "")]
    direct_emails: list[str] = []
    direct_phones: list[str] = []

    for tag in soup.find_all(True):
        href = str(tag.get("href") or "")
        data_cfemail = str(tag.get("data-cfemail") or "")
        if href.lower().startswith("mailto:"):
            direct_emails.extend(extract_emails(unquote(href[7:].split("?", 1)[0])))
        if href.lower().startswith("tel:"):
            normalized = validate_phone_number(unquote(href[4:].split("?", 1)[0]))
            if normalized:
                direct_phones.append(normalized)
        cloudflare_payload = data_cfemail or (href.split("#", 1)[1] if "/cdn-cgi/l/email-protection#" in href else "")
        if cloudflare_payload:
            direct_emails.extend(extract_emails(decode_cloudflare_hex(cloudflare_payload)))
        for attribute in ("data-email", "data-contact", "aria-label", "title"):
            value = tag.get(attribute)
            if value:
                values.append(str(value))

    return values, direct_emails, direct_phones


def extract_social_contacts(html: str) -> tuple[list[str], list[str]]:
    """Extract validated public email/phone values from raw public HTML."""

    values, direct_emails, direct_phones = _contact_values(html)
    emails: list[str] = []
    phones: list[str] = []
    for value in values:
        for email in extract_emails(value):
            if email not in emails:
                emails.append(email)
        for phone in extract_phones(value):
            normalized = validate_phone_number(phone)
            if normalized and normalized not in phones:
                phones.append(normalized)
    for email in [*direct_emails, *_obfuscated_emails(values)]:
        if email not in emails:
            emails.append(email)
    for phone in direct_phones:
        if phone not in phones:
            phones.append(phone)
    return emails, phones


def fetch_public_html(url: str) -> PublicHtmlPage | None:
    """Fetch one small public HTML page after URL-safety and robots checks."""

    current_url = url
    response = None
    for _ in range(MAX_SOCIAL_CONTACT_REDIRECTS + 1):
        if not is_safe_public_url(current_url) or not can_fetch_url(current_url, SOCIAL_CONTACT_USER_AGENT):
            return None
        time.sleep(float(getattr(settings, "APP_SOCIAL_CRAWL_DELAY_SECONDS", 0.5)))
        try:
            response = requests.get(
                current_url,
                headers={
                    "User-Agent": SOCIAL_CONTACT_USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.8",
                },
                timeout=float(getattr(settings, "APP_REQUEST_TIMEOUT_SECONDS", 15)),
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException:
            return None
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("location")
            response.close()
            if not location:
                return None
            current_url = urljoin(current_url, location)
            continue
        break
    else:
        return None

    if response is None or response.status_code >= 400 or not is_safe_public_url(current_url):
        if response is not None:
            response.close()
        return None
    if "html" not in response.headers.get("content-type", "").lower():
        response.close()
        return None

    body = bytearray()
    try:
        for chunk in response.iter_content(chunk_size=65_536):
            body.extend(chunk)
            if len(body) > MAX_SOCIAL_CONTACT_BYTES:
                return None
    finally:
        response.close()
    page_html = bytes(body).decode(response.encoding or "utf-8", errors="replace")
    return PublicHtmlPage(
        url=current_url,
        html=page_html,
        title=extract_page_title(page_html),
        text=" ".join(
            filter(None, [extract_page_title(page_html), extract_meta_description(page_html), extract_visible_text(page_html)])
        )[:12_000],
        links=extract_links(page_html, current_url),
    )


def crawl_social_contact_pages(urls: list[str]) -> list[SocialContactPage]:
    """Fetch a deduplicated, bounded set of public bio-link pages once each."""

    limit = max(1, min(int(getattr(settings, "APP_MAX_SOCIAL_CONTACT_PAGES", 5)), 10))
    pages: list[SocialContactPage] = []
    seen: set[str] = set()
    for url in urls:
        if url in seen or not is_safe_public_url(url):
            continue
        seen.add(url)
        page = fetch_public_html(url)
        if page is None:
            continue
        emails, phones = extract_social_contacts(page.html)
        pages.append(
            SocialContactPage(
                url=page.url,
                title=page.title,
                text=page.text,
                links=page.links,
                emails=emails,
                phones=phones,
            )
        )
        if len(pages) >= limit:
            break
    return pages


def crawl_and_extract_social_contacts(urls: list[str]) -> dict[str, list[str]]:
    """Return deduplicated public contacts plus the pages that supplied them.

    This compact mapping keeps the original pipeline-facing API simple while
    ``crawl_social_contact_pages()`` remains available when field-level source
    evidence is needed.
    """

    pages = crawl_social_contact_pages(urls)
    return {
        "emails": list(dict.fromkeys(email for page in pages for email in page.emails)),
        "phones": list(dict.fromkeys(phone for page in pages for phone in page.phones)),
        "pages": [page.url for page in pages],
    }
