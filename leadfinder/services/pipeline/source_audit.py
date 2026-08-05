from __future__ import annotations

import re
from urllib.parse import urlparse

import tldextract

from leadfinder.utils.normalize import normalize_text


DOMAIN_EXTRACTOR = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "aol.com",
    "icloud.com",
    "mail.com",
    "msn.com",
    "proton.me",
    "protonmail.com",
}

BLOCKED_CONTACT_EMAIL_DOMAINS = {
    "1outlets.com",
    "abebooks.com",
    "amazon.ca",
    "amazon.co.uk",
    "amazon.com",
    "archive.org",
    "barnesandnoble.com",
    "biblio.com",
    "blogger.com",
    "blogspot.com",
    "bookbub.com",
    "bookshop.org",
    "booktopia.com.au",
    "booksamillion.com",
    "christianbook.com",
    "domain.com",
    "ebay.com",
    "etsy.com",
    "example.com",
    "fantasticfiction.co.uk",
    "fantasticfiction.com",
    "goodreads.com",
    "harvard.edu",
    "librarything.com",
    "litcharts.com",
    "loc.gov",
    "mit.edu",
    "mitpressbookstore.mit.edu",
    "openlibrary.org",
    "scholastic.com",
    "shopify.com",
    "sparknotes.com",
    "squarespace.com",
    "stanford.edu",
    "target.com",
    "template.com",
    "walmart.com",
    "weebly.com",
    "wikipedia.org",
    "wikidata.org",
    "wix.com",
    "wixsite.com",
    "wordpress.com",
    "worldcat.org",
    "yale.edu",
}

GENERIC_ADMIN_EMAIL_PREFIXES = {
    "abuse",
    "admin",
    "administrator",
    "billing",
    "careers",
    "customer",
    "feedback",
    "help",
    "jobs",
    "no-reply",
    "noreply",
    "privacy",
    "service",
    "support",
    "tech",
    "technical",
    "webmaster",
}

CATALOG_OR_PLATFORM_HOST_PARTS = {
    "1outlets.",
    "abebooks.",
    "academia.edu",
    "amazon.",
    "anyflip.",
    "archive.org",
    "audible.",
    "barnesandnoble.",
    "beenverified.",
    "biblio.",
    "bookbub.",
    "bookdepository.",
    "bookshop.",
    "bookstore.",
    "booksamillion.",
    "booktopia.",
    "britannica.",
    "calameo.",
    "christianbook.",
    "clue360.",
    "cyberbackgroundchecks.",
    "d-pdf.",
    "dokumen.",
    "ebay.",
    "epub.",
    "etsy.",
    "facebook.",
    "fandom.",
    "fantasticfiction.",
    "fastpeoplesearch.",
    "findpeoplesearch.",
    "fliphtml5.",
    "free-ebooks.",
    "goodreads.",
    "harvard.edu",
    "hotmart.",
    "infobooks.",
    "instagram.",
    "instantcheckmate.",
    "intelius.",
    "issuu.",
    "kobo.",
    "librarything.",
    "linkedin.",
    "litcharts.",
    "loc.gov",
    "mit.edu",
    "mitpressbookstore.",
    "mylife.",
    "oceanofpdf.",
    "onlinebookclub.",
    "openlibrary.",
    "oujdalibrary.",
    "pdfcookie.",
    "pdfdrive.",
    "peoplebyname.",
    "peoplefinders.",
    "pinterest.",
    "radaris.",
    "readanybook.",
    "researchgate.",
    "scribd.",
    "slideshare.",
    "sparknotes.",
    "spokeo.",
    "stanford.edu",
    "target.com",
    "teachingbooks.",
    "thriftbooks.",
    "tiktok.",
    "truepeoplesearch.",
    "truthfinder.",
    "twitter.",
    "usphonebook.",
    "walmart.com",
    "whitepages.",
    "wikiwand.",
    "wikidata.",
    "wikipedia.",
    "worldcat.",
    "x.com",
    "yale.edu",
    "youtu.be",
    "youtube.",
}

PUBLISHER_DOMAIN_HINT_RE = re.compile(
    r"\b(press|publishing|publisher|imprint|publicity|media|literary|agency|booksforkids)\b",
    re.I,
)

CONTACT_ROLE_HINT_RE = re.compile(
    r"\b(contact|email|e-mail|booking|bookings|school visit|school visits|speaking|"
    r"publicity|publicist|press|media|agent|agency|represented|rights|submissions)\b",
    re.I,
)


def registered_domain_from_host(host: str) -> str:
    if not host:
        return ""
    extracted = DOMAIN_EXTRACTOR(host.lower())
    if extracted.domain and extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}".lower()
    return host.lower()


def registered_domain_from_url(url: str) -> str:
    return registered_domain_from_host(urlparse(url or "").hostname or "")


def registered_domain_from_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    return registered_domain_from_host(email.rsplit("@", 1)[1])


def email_local_part(email: str) -> str:
    if not email or "@" not in email:
        return ""
    return email.split("@", 1)[0].lower()


def host_matches_any(url: str, host_parts: set[str]) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return any(part in host for part in host_parts)


def is_catalog_or_platform_source(url: str) -> bool:
    return host_matches_any(url, CATALOG_OR_PLATFORM_HOST_PARTS)


def is_untrusted_contact_email_domain(email: str) -> bool:
    domain = registered_domain_from_email(email)
    if not domain:
        return True
    return any(domain == blocked or domain.endswith("." + blocked) for blocked in BLOCKED_CONTACT_EMAIL_DOMAINS)


def has_generic_admin_prefix(email: str) -> bool:
    local = email_local_part(email)
    return local in GENERIC_ADMIN_EMAIL_PREFIXES


def email_domain_matches_source(email: str, source_url: str) -> bool:
    email_domain = registered_domain_from_email(email)
    source_domain = registered_domain_from_url(source_url)
    if not email_domain or not source_domain:
        return False
    return (
        email_domain == source_domain
        or email_domain.endswith("." + source_domain)
        or source_domain.endswith("." + email_domain)
    )


def compact(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_text(value))


def author_tokens(author_name: str | None) -> list[str]:
    stopwords = {"author", "by", "dr", "mr", "mrs", "ms", "prof"}
    return [
        token
        for token in normalize_text(author_name).split()
        if len(token) >= 3 and token not in stopwords
    ]


def title_tokens(book_title: str | None) -> list[str]:
    stopwords = {
        "about",
        "amazon",
        "and",
        "author",
        "book",
        "books",
        "childrens",
        "children",
        "contact",
        "edition",
        "for",
        "from",
        "hardcover",
        "kids",
        "kindle",
        "official",
        "paperback",
        "picture",
        "pictures",
        "read",
        "reading",
        "story",
        "stories",
        "the",
        "website",
        "with",
        "young",
    }
    seen: set[str] = set()
    tokens: list[str] = []
    for token in normalize_text(book_title).split():
        if len(token) < 4 or token in stopwords or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def author_identity_appears(
    author_name: str | None,
    book_title: str | None,
    *values: str | None,
    allow_title_bridge: bool = True,
) -> bool:
    tokens = author_tokens(author_name)
    if not tokens:
        return False
    text = normalize_text(" ".join(value or "" for value in values))
    compact_text = compact(text)
    phrase = " ".join(tokens)
    compact_author = "".join(tokens)
    if phrase and phrase in text:
        return True
    if compact_author and compact_author in compact_text:
        return True
    if len(tokens) >= 2 and all(token in text or token in compact_text for token in tokens):
        return True
    if tokens[-1] in text and len(tokens[-1]) >= 5:
        return True
    if not allow_title_bridge:
        return False
    title_matches = sum(1 for token in title_tokens(book_title) if token in text or token in compact_text)
    return tokens[-1] in text and title_matches >= min(2, len(title_tokens(book_title)))


def source_has_contact_role_hint(*values: str | None) -> bool:
    return bool(CONTACT_ROLE_HINT_RE.search(" ".join(value or "" for value in values)))


def looks_like_publisher_or_agency_site(url: str, *values: str | None) -> bool:
    if not url or is_catalog_or_platform_source(url):
        return False
    host = (urlparse(url).hostname or "").lower().replace("-", " ")
    text = " ".join([host, *(value or "" for value in values)])
    return bool(PUBLISHER_DOMAIN_HINT_RE.search(text))


def evidence_source_is_trusted_for_contact(
    *,
    author_name: str | None,
    book_title: str | None,
    field_name: str,
    field_value: str,
    source_url: str,
    evidence_type: str,
    source_title: str = "",
    source_snippet: str = "",
) -> bool:
    if not field_value or not source_url:
        return False
    is_direct_social_evidence = evidence_type == "social_profile"
    if is_catalog_or_platform_source(source_url) and not is_direct_social_evidence:
        return False

    verified_types = {
        "contact_page",
        "official_author_site",
        "publisher_site",
        "social_profile",
        "groq_extraction",
        "manual",
    }
    if evidence_type not in verified_types:
        return False

    identity_match = author_identity_appears(
        author_name,
        book_title,
        source_url,
        source_title,
        source_snippet,
        allow_title_bridge=True,
    )

    if is_direct_social_evidence:
        if not identity_match:
            return False
        if field_name in {"public_email", "representation_email", "publicist_email"}:
            return not is_untrusted_contact_email_domain(field_value) and not has_generic_admin_prefix(field_value)
        if field_name == "public_phone":
            return True
        return identity_match

    if field_name in {"public_email", "representation_email", "publicist_email"}:
        if is_untrusted_contact_email_domain(field_value) or has_generic_admin_prefix(field_value):
            return False
        local = compact(email_local_part(field_value))
        tokens = author_tokens(author_name)
        source_domain_text = compact(registered_domain_from_url(source_url))
        domain_mentions_author = any(token in source_domain_text for token in tokens if len(token) >= 4)
        local_mentions_author = bool(tokens and (''.join(tokens) in local or tokens[-1] in local))
        if email_domain_matches_source(field_value, source_url) and (
            identity_match
            or domain_mentions_author
            or field_name in {"representation_email", "publicist_email"}
        ):
            return True
        if field_name == "public_email":
            return identity_match or local_mentions_author
        return (
            identity_match
            or source_has_contact_role_hint(source_title, source_snippet)
            or looks_like_publisher_or_agency_site(source_url, source_title, source_snippet)
        )

    if field_name == "public_phone":
        return identity_match or source_has_contact_role_hint(source_url, source_title, source_snippet)

    return identity_match
