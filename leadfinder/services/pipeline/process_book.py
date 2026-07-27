from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import tldextract

logger = logging.getLogger(__name__)

from django.conf import settings

from leadfinder.models import (
    AuthorProfile,
    Evidence,
    Lead,
    SalesAgentBrief,
    SearchQueryLog,
    SearchResult,
    VideoEvidence,
    AgentThought,
)

def log_agent_thought(run, agent_name: str, message: str) -> None:
    try:
        AgentThought.objects.create(research_run=run, agent_name=agent_name, message=message)
    except Exception:
        pass

from leadfinder.services.ai.classify_book import classify_book
from leadfinder.services.ai.classify_video import choose_video_status, classify_video
from leadfinder.services.ai.extract_contact import extract_contact_data
from leadfinder.services.ai.reconcile_lead import reconcile_and_verify_lead
from leadfinder.services.ai.summarize_sales_brief import render_brief_markdown, summarize_sales_brief
from leadfinder.services.crawl.extract_links import extract_links, extract_social_links
from leadfinder.services.crawl.extract_text import extract_page_title, extract_visible_text
from leadfinder.services.crawl.contact_regex import extract_emails, extract_phones
from leadfinder.services.crawl.safe_fetch import candidate_author_pages, safe_fetch
from leadfinder.services.books.isbn_intelligence import (
    analyze_identifier,
    public_resolution_to_book_data,
    resolve_free_metadata,
)
from leadfinder.services.pipeline.cancellation import raise_if_run_canceled
from leadfinder.services.pipeline.lead_validator import is_highly_valid_contact_email, validate_phone_number
from leadfinder.services.pipeline.quality_gate import has_verified_contact_source, lead_verification_errors
from leadfinder.services.pipeline.source_audit import (
    email_domain_matches_source,
    evidence_source_is_trusted_for_contact,
    is_catalog_or_platform_source,
    is_untrusted_contact_email_domain,
    looks_like_publisher_or_agency_site,
)
from leadfinder.services.scoring.lead_score import score_from_lead
from leadfinder.services.search import get_search_provider
from leadfinder.services.search.video_provider import search_youtube_api
from leadfinder.utils.normalize import normalized_author_key, is_valid_author_name, normalize_text
from leadfinder.utils.source_confidence import clamp_confidence
from leadfinder.utils.url_safety import is_safe_public_url

DOMAIN_EXTRACTOR = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


SOCIAL_CLASSES = {
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "vimeo.com": "vimeo",
    "instagram.com": "instagram",
    "facebook.com": "facebook",
    "tiktok.com": "tiktok",
    "linkedin.com": "linkedin",
    "goodreads.com": "goodreads",
}

UNTRUSTED_AUTHOR_SITE_HOST_PARTS = {
    "amazon.",
    "audible.",
    "barnesandnoble.",
    "bookshop.",
    "booksamillion.",
    "biblio.",
    "ebay.",
    "etsy.",
    "facebook.",
    "goodreads.",
    "hotmart.",
    "instagram.",
    "kobo.",
    "linkedin.",
    "pinterest.",
    "tiktok.",
    "twitter.",
    "x.com",
    "youtube.",
    "youtu.be",
    "infobooks.",
    "pdfdrive.",
    "free-ebooks.",
    "epub.pub",
    "d-pdf.",
    "readanybook.",
    "oceanofpdf.",
    "pdfcookie.",
    "anyflip.",
    "fliphtml5.",
    "yumpu.",
    "calameo.",
    "scribd.",
    "slideshare.",
    "issuu.",
    "academia.edu",
    "researchgate.",
    "spokeo.",
    "whitepages.",
    "mylife.",
    "radaris.",
    "beenverified.",
    "truthfinder.",
    "instantcheckmate.",
    "peoplefinders.",
    "intelius.",
    "peekyou.",
    "fastpeoplesearch.",
    "truepeoplesearch.",
    "usphonebook.",
    "clue360.",
    "cyberbackgroundchecks.",
    "officialusa.",
    "peoplebyname.",
    "findpeoplesearch.",
    "abebooks.",
    "thriftbooks.",
    "target.com",
    "walmart.com",
    "linktr.ee",
    "linktree",
    "1outlets.",
    "dokumen.",
    "biblionix.",
    "onlinebookclub.",
    "oujdalibrary.",
    "eric.ed.gov",
    "unlv.edu",
    "udel.edu",
    "wikipedia.",
    "wikidata.",
    "britannica.",
    "behindthename.",
    "epicgames.",
    "fandom.",
    "wikiwand.",
    "openlibrary.",
    "archive.org",
    "librarything.",
    "worldcat.",
    "loc.gov",
    "fantasticfiction.",
    "bookbub.com",
    "litcharts.com",
    "sparknotes.com",
    "mitpressbookstore.",
    "mit.edu",
    "harvard.edu",
    "yale.edu",
    "stanford.edu",
    "scholastic.",
    "penguinrandomhouse.",
    "harpercollins.",
    "simonandschuster.",
    "macmillan.com",
    "hachettebookgroup.",
    "bloomsbury.",
    "booklife.",
}

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

CONTACT_INTENT_RE = re.compile(
    r"\b(contact|email|e-mail|mail|reach|booking|bookings|school visit|school visits|"
    r"speaking|publicity|publicist|press|media|agent|agency|represented|website|official)\b",
    re.I,
)

TITLE_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "about",
    "book",
    "books",
    "childrens",
    "children",
    "kids",
    "picture",
    "pictures",
    "story",
    "stories",
    "storytime",
    "author",
    "official",
    "website",
    "contact",
    "amazon",
    "kindle",
    "paperback",
    "hardcover",
    "edition",
    "series",
    "volume",
    "first",
    "young",
    "read",
    "reading",
    "write",
    "writing",
    "guide",
    "visual",
    "art",
}

NAME_STOPWORDS = {"dr", "mr", "ms", "mrs", "prof", "author", "by"}


def classify_result_url(url: str) -> tuple[str, float]:
    lower = url.lower()
    if "amazon." in lower and ("/dp/" in lower or "/gp/product/" in lower or "/product/" in lower):
        return "amazon_book", 0.9
    for domain, classification in SOCIAL_CLASSES.items():
        if domain in lower:
            return classification, 0.85
    if is_catalog_or_platform_source(url):
        return "unrelated", 0.2
    if looks_like_publisher_or_agency_site(url):
        return "publisher_site", 0.55
    return "author_site", 0.45


def author_discovery_queries(book) -> list[str]:
    author = book.author_name
    title = book.title
    if not author:
        return []
    return [
        f'"{author}" "{title}" author website',
        f'"{author}" "{title}" contact',
        f'"{author}" "{title}" official author site',
        f'"{author}" "{title}" media kit',
        f'"{author}" "{title}" school visits',
        f'"{author}" children\'s book author',
        f'"{author}" picture book author',
        f'"{author}" author visits contact',
        f'"{author}" booking email children author',
        f'"{title}" "{author}" official website',
        f'"{title}" "{author}" publisher',
        f'"{author}" "{title}" Instagram',
        f'"{author}" "{title}" Facebook',
        f'"{author}" "{title}" YouTube',
        f'"{author}" "{title}" book trailer',
        f'"{author}" "{title}" email',
        f'"{author}" "{title}" phone',
        f'"{author}" "{title}" booking contact',
        f'site:instagram.com "{author}" "{title}" email',
        f'site:facebook.com "{author}" "{title}" email',
        f'site:facebook.com "{author}" "{title}" phone',
        f'site:linkedin.com "{author}" "{title}" contact',
        f'site:youtube.com "{author}" "{title}" email',
    ]

def deep_contact_discovery_queries(book) -> list[str]:
    author = book.author_name
    title = book.title
    if not author:
        return []
    return [
        f'"{author}" official website',
        f'"{author}" author website contact',
        f'"{author}" "{title}" official website',
        f'"{author}" "{title}" contact email',
        f'"{author}" children\'s author contact email',
        f'"{author}" picture book author contact',
        f'"{author}" school visits booking contact',
        f'"{author}" media kit contact',
        f'"{author}" email "@gmail.com" OR "@yahoo.com" OR "@outlook.com"',
        f'"{author}" ("agent" OR "agency" OR "represented by") contact',
        f'"{author}" ("publicist" OR "publicity" OR "press" OR "media") email',
        f'"{author}" contact page',
    ]


def video_queries(book) -> list[str]:
    author = book.author_name
    title = book.title
    return [
        f'"{title}" "{author}" book trailer',
        f'"{title}" "{author}" animated trailer',
        f'"{title}" "{author}" animation',
        f'"{title}" "{author}" animated book',
        f'"{title}" "{author}" read aloud',
        f'"{author}" children\'s book trailer',
        f'"{title}" children book trailer',
    ]


def _domain_is_retail_or_social(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return is_catalog_or_platform_source(url) or any(token in host for token in UNTRUSTED_AUTHOR_SITE_HOST_PARTS)


def _registered_domain(url: str) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    if not host:
        return ""
    extracted = DOMAIN_EXTRACTOR(host)
    if extracted.domain and extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}".lower()
    return host


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_text(value))


def _author_tokens(author_name: str | None) -> list[str]:
    return [
        token
        for token in normalize_text(author_name).split()
        if len(token) >= 3 and token not in NAME_STOPWORDS
    ]


def _title_tokens(title: str | None) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for token in normalize_text(title).split():
        if len(token) < 4 or token in TITLE_STOPWORDS or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def _identity_match_in_text(text: str, book, *, allow_title_bridge: bool = True) -> bool:
    normalized = normalize_text(text)
    compact = _compact(text)
    author_tokens = _author_tokens(book.author_name)
    if not author_tokens:
        return False

    author_phrase = " ".join(author_tokens)
    author_compact = "".join(author_tokens)
    if author_phrase and author_phrase in normalized:
        return True
    if author_compact and author_compact in compact:
        return True
    if len(author_tokens) >= 2 and all(token in normalized for token in author_tokens):
        return True

    if not allow_title_bridge:
        return False

    title_tokens = _title_tokens(book.title)
    matched_title_count = sum(1 for token in title_tokens if token in normalized or token in compact)
    required_title_matches = min(2, len(title_tokens))
    if required_title_matches and author_tokens[-1] in normalized and matched_title_count >= required_title_matches:
        return True

    return False


def _url_or_title_matches_identity(url: str, title: str, book) -> bool:
    return _identity_match_in_text(f"{url} {title}", book)


def _social_url_matches_identity(url: str, book) -> bool:
    parsed = urlparse(url)
    handle_text = f"{parsed.path} {parsed.netloc}"
    return _identity_match_in_text(handle_text, book, allow_title_bridge=False)


def _trusted_author_site_url(url: str, book, title: str = "") -> bool:
    if not url or not is_safe_public_url(url):
        return False
    if _domain_is_retail_or_social(url):
        return False
    return _url_or_title_matches_identity(url, title, book)


def _filter_socials_for_identity(socials: dict[str, str], book) -> dict[str, str]:
    return {field: url for field, url in socials.items() if _social_url_matches_identity(url, book)}


def _filter_extraction_urls(extraction, book, canonical_url: str):
    if extraction.canonical_website and not _trusted_author_site_url(extraction.canonical_website, book):
        extraction.warnings.append(f"Dropped unverified official website candidate: {extraction.canonical_website}")
        extraction.canonical_website = None
    if extraction.contact_page_url and not _trusted_author_site_url(extraction.contact_page_url, book):
        extraction.warnings.append(f"Dropped unverified contact page candidate: {extraction.contact_page_url}")
        extraction.contact_page_url = None
    for field in ["instagram_url", "facebook_url", "tiktok_url", "youtube_url", "linkedin_url"]:
        value = getattr(extraction, field)
        if value and not _social_url_matches_identity(value, book):
            extraction.warnings.append(f"Dropped social profile that did not match the author identity: {value}")
            setattr(extraction, field, None)
    if extraction.publisher_url and extraction.publisher_url == canonical_url:
        extraction.publisher_url = None
    if extraction.publisher_url and is_catalog_or_platform_source(extraction.publisher_url):
        extraction.warnings.append(f"Dropped catalog/bookstore URL misclassified as publisher: {extraction.publisher_url}")
        extraction.publisher_url = None
    return extraction


def _source_supports_contact_field(field: str, value: str, source_url: str, book, *, source_title: str = "", source_snippet: str = "") -> bool:
    return evidence_source_is_trusted_for_contact(
        author_name=book.author_name,
        book_title=book.title,
        field_name=field,
        field_value=value,
        source_url=source_url,
        evidence_type="contact_page",
        source_title=source_title,
        source_snippet=source_snippet,
    )


def _contact_source_urls(extraction, field: str, default_source_url: str) -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = []
    for item in extraction.evidence:
        if item.get("field") != field:
            continue
        source_url = item.get("source_url") or default_source_url
        reason = item.get("reason") or ""
        if source_url:
            sources.append((source_url, reason))
    if default_source_url and not sources:
        sources.append((default_source_url, ""))
    return sources


def _drop_untrusted_extracted_contacts(extraction, book, default_source_url: str):
    for field in ["public_email", "public_phone", "representation_email", "publicist_email"]:
        value = getattr(extraction, field)
        if not value:
            continue
        sources = _contact_source_urls(extraction, field, default_source_url)
        trusted = any(
            _source_supports_contact_field(field, value, source_url, book, source_snippet=reason)
            for source_url, reason in sources
        )
        if trusted:
            continue
        extraction.warnings.append(
            f"Dropped {field} because its source was not an author/agent/publisher contact page for this book."
        )
        setattr(extraction, field, None)
        extraction.evidence = [
            item
            for item in extraction.evidence
            if not (item.get("field") == field and item.get("value") == value)
        ]
    return extraction


def _email_matches_author_or_trusted_source(email: str, book, source_url: str, *, trusted_source: bool) -> bool:
    if not email or not is_highly_valid_contact_email(email):
        return False
    if is_catalog_or_platform_source(source_url) or is_untrusted_contact_email_domain(email):
        return False
    local_part, domain = email.lower().split("@", 1)
    local_compact = _compact(local_part)
    author_tokens = _author_tokens(book.author_name)
    if not author_tokens:
        return False

    source_domain = _registered_domain(source_url)
    email_domain = domain.lower()
    author_compact = "".join(author_tokens)

    if trusted_source and email_domain_matches_source(email, source_url):
        return True

    if trusted_source and email_domain not in FREE_EMAIL_DOMAINS:
        return True

    if author_compact and author_compact in local_compact:
        return True
    if author_tokens[-1] in local_compact and len(author_tokens[-1]) >= 4:
        return True
    if len(author_tokens) >= 2 and all(token in local_compact for token in author_tokens[:2]):
        return True

    return False


def _search_result_has_contact_context(dto) -> bool:
    return bool(CONTACT_INTENT_RE.search(" ".join(filter(None, [dto.title, dto.snippet or "", dto.url]))))


def _create_evidence_for_contact(lead, author_profile, extraction, default_source_url: str, book) -> None:
    for item in extraction.evidence:
        field = item.get("field")
        value = item.get("value")
        if not field or not value:
            continue
        source_url = item.get("source_url") or default_source_url
        evidence_type = "groq_extraction" if item.get("reason", "").lower().startswith("groq") else "contact_page"
        if field in {"public_email", "public_phone", "representation_email", "publicist_email"}:
            if not _source_supports_contact_field(
                field,
                value,
                source_url,
                book,
                source_title=item.get("source_title") or "",
                source_snippet=item.get("reason") or "",
            ):
                continue
        Evidence.objects.create(
            lead=lead,
            author_profile=author_profile,
            evidence_type=evidence_type,
            field_name=field,
            field_value=value,
            source_url=source_url,
            source_snippet=item.get("reason") or "",
            confidence=clamp_confidence(item.get("confidence") or extraction.confidence),
            is_primary=True,
        )


def _extract_public_contact_from_search_result(dto, result_class: str, book) -> list[dict]:
    text = " ".join(filter(None, [dto.title, dto.snippet or ""]))
    contacts: list[dict] = []
    trusted_author_source = result_class == "author_site" and _trusted_author_site_url(dto.url, book, dto.title)
    trusted_social_source = (
        result_class in {"instagram", "facebook", "tiktok", "linkedin", "youtube"}
        and _social_url_matches_identity(dto.url, book)
    )
    has_contact_context = _search_result_has_contact_context(dto)
    if not (trusted_author_source or trusted_social_source or has_contact_context):
        return contacts

    for email in extract_emails(text):
        trusted_source = trusted_author_source or trusted_social_source
        if not _email_matches_author_or_trusted_source(email, book, dto.url, trusted_source=trusted_source):
            continue
        contacts.append(
            {
                "field": "public_email",
                "value": email,
                "source_url": dto.url,
                "source_title": dto.title,
                "source_snippet": dto.snippet or "",
                "evidence_type": "social_profile" if trusted_social_source else ("contact_page" if trusted_author_source else "web_search_result"),
                "confidence": 0.72 if trusted_author_source else (0.65 if trusted_social_source else 0.52),
            }
        )
    for phone in extract_phones(text):
        validated_phone = validate_phone_number(phone)
        if not validated_phone or not (trusted_author_source or trusted_social_source):
            continue
        contacts.append(
            {
                "field": "public_phone",
                "value": validated_phone,
                "source_url": dto.url,
                "source_title": dto.title,
                "source_snippet": dto.snippet or "",
                "evidence_type": "social_profile" if trusted_social_source else "contact_page",
                "confidence": 0.62 if trusted_social_source else 0.68,
            }
        )
    return contacts


def _contact_result_matches_book_or_author(dto, book) -> bool:
    text = " ".join(filter(None, [dto.title, dto.snippet or "", getattr(dto, "url", "")]))
    return _identity_match_in_text(text, book)


def _clear_unverified_lead_contacts(lead, author_profile) -> None:
    changed_fields: list[str] = []
    warnings = list(lead.warnings_json or [])
    for field in ["public_email", "public_phone", "representation_email", "publicist_email"]:
        value = getattr(lead, field)
        if not value:
            continue
        min_confidence = 0.55 if field == "public_phone" else 0.6
        if has_verified_contact_source(lead, field, value, min_confidence=min_confidence):
            continue
        setattr(lead, field, "")
        changed_fields.append(field)
        warnings.append(f"Cleared {field}: no trusted author/agent/publisher source verified the value.")

    if changed_fields:
        lead.warnings_json = warnings
        lead.save(update_fields=[*changed_fields, "warnings_json", "updated_at"])
        if author_profile:
            profile_fields: list[str] = []
            if "representation_email" in changed_fields and author_profile.representation_email:
                author_profile.representation_email = ""
                profile_fields.append("representation_email")
            if "publicist_email" in changed_fields and author_profile.publicist_email:
                author_profile.publicist_email = ""
                profile_fields.append("publicist_email")
            if profile_fields:
                author_profile.save(update_fields=[*profile_fields, "updated_at"])


def process_book(book, run_video_search: bool = True, run_ai_extraction: bool = True) -> Lead:
    raise_if_run_canceled(book.research_run_id)
    log_agent_thought(book.research_run, "Harvester", f"Harvester details retrieval started for book: '{book.title}'")
    amazon_author_url = ""
    if book.asin:
        try:
            # Check if we already have successfully scraped details for this ASIN in the database from a previous book/run
            from leadfinder.models import Book as DBBook
            cached_book = None
            current_identifier = analyze_identifier(book.asin)
            for b in DBBook.objects.filter(asin=book.asin).exclude(author_name="").order_by("-book_data_confidence"):
                if is_valid_author_name(b.author_name):
                    if (
                        current_identifier.identifier_type in {"isbn10", "isbn13"}
                        and not (b.source_raw_json or {}).get("metadata_resolution")
                    ):
                        continue
                    cached_book = b
                    break

            am_res = None
            if cached_book and (cached_book.review_count is not None or cached_book.rating is not None or cached_book.publisher):
                logger.info(f"Reusing cached Amazon details for ASIN {book.asin} from book {cached_book.id}")
                am_res = {
                    "scraped_successfully": True,
                    "title": cached_book.title,
                    "review_count": cached_book.review_count,
                    "rating": cached_book.rating,
                    "publisher": cached_book.publisher,
                    "publication_date": cached_book.publication_date,
                    "cover_image_url": cached_book.cover_image_url,
                    "has_aplus_content": cached_book.has_aplus_content,
                    "authors": [{"name": cached_book.author_name, "url": ""}],
                    "description": cached_book.amazon_source_snippet,
                }
                ap = AuthorProfile.objects.filter(author_name=cached_book.author_name).first()
                if ap and ap.amazon_author_url:
                    am_res["authors"][0]["url"] = ap.amazon_author_url

            if not am_res:
                identifier = analyze_identifier(book.asin)
                if identifier.identifier_type in {"isbn10", "isbn13"} and identifier.valid:
                    log_agent_thought(
                        book.research_run,
                        "Harvester",
                        f"Reconciling {identifier.display} across public Open Library and Google Books records.",
                    )
                    resolution = resolve_free_metadata(identifier.canonical)
                    am_res = public_resolution_to_book_data(resolution)
                    raw = dict(book.source_raw_json or {})
                    raw["identifier_intelligence"] = resolution.get("identifier", {})
                    raw["metadata_resolution"] = {
                        "confidence": resolution.get("confidence", 0),
                        "warnings": resolution.get("warnings", []),
                        "sources": resolution.get("sources", []),
                        "field_evidence": resolution.get("field_evidence", {}),
                    }
                    book.source_raw_json = raw

                if not am_res or not am_res.get("authors"):
                    log_agent_thought(
                        book.research_run,
                        "Harvester",
                        f"Public catalogs were incomplete for {book.asin}; checking indexed public search evidence.",
                    )
                    from leadfinder.services.amazon.amazon_scraper import fallback_amazon_book_page

                    fallback = fallback_amazon_book_page(book.asin, use_ai=run_ai_extraction, book_title=book.title)
                    if am_res:
                        for key, value in fallback.items():
                            if value and not am_res.get(key):
                                am_res[key] = value
                    else:
                        am_res = fallback

            if am_res and (am_res.get("scraped_successfully") or am_res.get("title")):
                if am_res.get("title"):
                    book.title = am_res["title"]
                if am_res.get("review_count") is not None:
                    book.review_count = am_res["review_count"]
                if am_res.get("rating") is not None:
                    book.rating = am_res["rating"]
                if am_res.get("publisher") and not book.publisher:
                    book.publisher = am_res["publisher"]
                if am_res.get("publication_date") and not book.publication_date:
                    book.publication_date = am_res["publication_date"]
                if am_res.get("cover_image_url") and not book.cover_image_url:
                    book.cover_image_url = am_res["cover_image_url"]
                if am_res.get("has_aplus_content") is not None:
                    book.has_aplus_content = am_res["has_aplus_content"]
                
                # Update author details - always trust ground-truth scraped author name
                if am_res.get("authors"):
                    first_author = am_res["authors"][0]
                    if first_author.get("name"):
                        if not book.author_name or not is_valid_author_name(book.author_name) or am_res.get("scraped_successfully"):
                            book.author_name = first_author["name"]
                        if first_author.get("url"):
                            amazon_author_url = first_author["url"]
                
                metadata_sources = am_res.get("metadata_sources") or []
                if metadata_sources:
                    for source in metadata_sources:
                        Evidence.objects.create(
                            book=book,
                            evidence_type="web_search_result",
                            field_name="book_metadata",
                            field_value=f"Title: {source.get('title') or book.title}; Authors: {', '.join(source.get('authors') or [])}",
                            source_url=source.get("source_url"),
                            source_title=f"{source.get('provider', 'Public catalog').replace('_', ' ').title()} metadata",
                            source_snippet=(source.get("description") or "")[:500],
                            confidence=float(am_res.get("metadata_confidence") or 0.65),
                            is_primary=True,
                        )
                
                # Use description in classification snippets
                if am_res.get("description"):
                    if not book.amazon_source_snippet:
                        book.amazon_source_snippet = am_res["description"]
                    else:
                        book.amazon_source_snippet = f"{book.amazon_source_snippet}\n\nDescription: {am_res['description']}"
                book.save()
        except Exception as exc:
            logger.error(f"Error enriching book with Amazon scraper: {exc}")

    classification = classify_book(
        {
            "title": book.title,
            "author_name": book.author_name,
            "category": book.category,
            "publisher": book.publisher,
            "amazon_source_title": book.amazon_source_title,
            "amazon_source_snippet": book.amazon_source_snippet,
        },
        [book.amazon_source_snippet],
        use_ai=run_ai_extraction,
    )
    book.is_childrens_book = classification.is_childrens_book
    book.is_picture_or_illustrated_book = classification.is_picture_or_illustrated_book
    book.book_classification_confidence = classification.confidence
    book.book_classification_reason = classification.reason
    book.save()

    enrichment_provider = (book.research_run.settings_json or {}).get("enrichment_provider")
    provider = get_search_provider(enrichment_provider or book.research_run.source_provider)
    max_results = min(max(int(getattr(settings, "APP_MAX_SEARCH_RESULTS_PER_QUERY", 5)), 1), 10)
    max_author_queries = min(
        max(int(getattr(settings, "APP_MAX_AUTHOR_DISCOVERY_QUERIES", 5)), 1),
        len(author_discovery_queries(book)),
    )
    candidate_urls: list[str] = []
    publisher_url = ""
    socials: dict[str, str] = {}
    search_contact_evidence: list[dict] = []
    source_hints = book.source_raw_json or {}
    for field, url in (source_hints.get("booklife_social_links") or {}).items():
        if field.endswith("_url") and url and _social_url_matches_identity(url, book):
            socials.setdefault(field, url)
            Evidence.objects.create(
                book=book,
                evidence_type="social_profile",
                field_name=field,
                field_value=url,
                source_url=source_hints.get("booklife_detail_url") or book.amazon_source_url or url,
                confidence=0.65,
            )
    for url in source_hints.get("booklife_author_urls") or []:
        if _trusted_author_site_url(url, book):
            candidate_urls.append(url)
            Evidence.objects.create(
                book=book,
                evidence_type="official_author_site",
                field_name="booklife_author_url_hint",
                field_value=url,
                source_url=source_hints.get("booklife_detail_url") or book.amazon_source_url or url,
                confidence=0.6,
            )

    log_agent_thought(book.research_run, "Harvester", f"Searching for official website and socials for author '{book.author_name}'...")
    for query in author_discovery_queries(book)[:max_author_queries]:
        raise_if_run_canceled(book.research_run_id)
        log = SearchQueryLog.objects.create(research_run=book.research_run, book=book, query=query, provider=provider.provider_name)
        try:
            results = provider.search(query, max_results=max_results)
            log.result_count = len(results)
            log.status = "success"
        except Exception as exc:
            results = []
            log.status = "failed"
            log.error_message = str(exc)
        log.save()
        for dto in results:
            result_class, confidence = classify_result_url(dto.url)
            matches_identity = _contact_result_matches_book_or_author(dto, book)
            SearchResult.objects.create(
                search_query_log=log,
                title=dto.title[:500],
                url=dto.url,
                snippet=dto.snippet or "",
                rank=dto.rank,
                provider=dto.provider,
                classification=result_class,
                classification_confidence=confidence,
            )
            if result_class == "publisher_site" and matches_identity and not publisher_url:
                publisher_url = dto.url
            elif (
                result_class in {"instagram", "facebook", "tiktok", "linkedin", "youtube", "goodreads"}
                and matches_identity
                and _social_url_matches_identity(dto.url, book)
            ):
                field = f"{result_class}_url"
                socials.setdefault(field, dto.url)
            elif result_class == "author_site" and matches_identity and _trusted_author_site_url(dto.url, book, dto.title):
                candidate_urls.append(dto.url)
            if matches_identity:
                search_contact_evidence.extend(_extract_public_contact_from_search_result(dto, result_class, book))

    candidate_urls = list(dict.fromkeys(candidate_urls))
    canonical_url = candidate_urls[0] if candidate_urls else ""
    crawled_text = ""
    crawled_links: list[str] = []
    page_source_url = canonical_url
    if canonical_url:
        log_agent_thought(book.research_run, "Harvester", f"Crawling author website {canonical_url} to extract contact links and page content.")
        max_pages = int(getattr(settings, "APP_MAX_AUTHOR_PAGES_TO_CRAWL", 5))
        for page_url in candidate_author_pages(canonical_url)[:max_pages]:
            fetched = safe_fetch(page_url)
            if not fetched or fetched.status_code >= 400:
                continue
            page_source_url = fetched.url
            title = extract_page_title(fetched.html)
            text = extract_visible_text(fetched.html)
            links = extract_links(fetched.html, fetched.url)
            crawled_text = f"{crawled_text}\n{text}"[: int(getattr(settings, "APP_MAX_GROQ_INPUT_CHARS", 12000))]
            crawled_links.extend(link for link in links if link not in crawled_links)
            Evidence.objects.create(
                book=book,
                evidence_type="official_author_site",
                field_name="crawled_page",
                field_value=fetched.url,
                source_url=fetched.url,
                source_title=title[:500],
                source_snippet=text[:500],
                confidence=0.55,
            )
    socials.update(_filter_socials_for_identity(extract_social_links(crawled_links), book))

    extraction = extract_contact_data(
        book.author_name,
        book.title,
        canonical_url,
        page_source_url or canonical_url or "https://example.invalid/missing-source",
        crawled_text,
        crawled_links,
        use_ai=run_ai_extraction,
    )
    extraction = _filter_extraction_urls(extraction, book, canonical_url)
    extraction = _drop_untrusted_extracted_contacts(extraction, book, page_source_url or canonical_url)

    # DEEP TARGETED RE-SEARCH LAYER: If no direct contact is found in first pass, dig deeper!
    has_trusted_search_contact = any(
        contact.get("evidence_type") == "contact_page" and contact.get("confidence", 0) >= 0.65
        for contact in search_contact_evidence
    )
    if not extraction.public_email and not extraction.representation_email and not has_trusted_search_contact:
        logger.info(f"Initiating multi-layered Deep Search for author {book.author_name}...")
        log_agent_thought(book.research_run, "Harvester", f"Deep searching additional contact sources for '{book.author_name}'...")
        deep_candidate_urls = []
        deep_crawled_text = ""
        deep_crawled_links = []
        max_deep_queries = min(
            max(int(getattr(settings, "APP_MAX_DEEP_CONTACT_QUERIES", 5)), 1),
            len(deep_contact_discovery_queries(book)),
        )

        for query in deep_contact_discovery_queries(book)[:max_deep_queries]:
            raise_if_run_canceled(book.research_run_id)
            log = SearchQueryLog.objects.create(research_run=book.research_run, book=book, query=query, provider=provider.provider_name)
            try:
                results = provider.search(query, max_results=max_results)
                log.result_count = len(results)
                log.status = "success"
            except Exception as exc:
                results = []
                log.status = "failed"
                log.error_message = str(exc)
            log.save()
            for dto in results:
                result_class, confidence = classify_result_url(dto.url)
                matches_identity = _contact_result_matches_book_or_author(dto, book)
                SearchResult.objects.create(
                    search_query_log=log,
                    title=dto.title[:500],
                    url=dto.url,
                    snippet=dto.snippet or "",
                    rank=dto.rank,
                    provider=dto.provider,
                    classification=result_class,
                    classification_confidence=confidence,
                )
                if matches_identity:
                    search_contact_evidence.extend(_extract_public_contact_from_search_result(dto, result_class, book))
                    if result_class == "author_site" and _trusted_author_site_url(dto.url, book, dto.title):
                        deep_candidate_urls.append(dto.url)
                    elif result_class in {"instagram", "facebook", "tiktok", "linkedin", "youtube", "goodreads"} and _social_url_matches_identity(dto.url, book):
                        field = f"{result_class}_url"
                        socials.setdefault(field, dto.url)
            if any(
                contact.get("evidence_type") == "contact_page" and contact.get("confidence", 0) >= 0.65
                for contact in search_contact_evidence
            ) or len(deep_candidate_urls) >= int(getattr(settings, "APP_MAX_AUTHOR_PAGES_TO_CRAWL", 3)):
                break

        deep_candidate_urls = list(dict.fromkeys(deep_candidate_urls))
        # If we found any new candidate pages in deep search, crawl them to find contact email/phone.
        if deep_candidate_urls:
            max_pages = int(getattr(settings, "APP_MAX_AUTHOR_PAGES_TO_CRAWL", 3))
            for page_url in deep_candidate_urls[:max_pages]:
                if page_url == canonical_url:
                    continue
                fetched = safe_fetch(page_url)
                if not fetched or fetched.status_code >= 400:
                    continue
                title = extract_page_title(fetched.html)
                text = extract_visible_text(fetched.html)
                links = extract_links(fetched.html, fetched.url)
                deep_crawled_text = f"{deep_crawled_text}\n{text}"[:3000]
                deep_crawled_links.extend(link for link in links if link not in deep_crawled_links)
                Evidence.objects.create(
                    book=book,
                    evidence_type="official_author_site",
                    field_name="deep_crawled_page",
                    field_value=fetched.url,
                    source_url=fetched.url,
                    source_title=title[:500],
                    source_snippet=text[:500],
                    confidence=0.6,
                )

        if deep_crawled_text:
            # Re-run extraction merging the original and deep crawled data
            logger.info("Executing deep re-extraction step...")
            merged_text = f"{crawled_text}\n\n=== Deep Search Crawled Content ===\n{deep_crawled_text}"[: int(getattr(settings, "APP_MAX_GROQ_INPUT_CHARS", 12000))]
            merged_links = list(set(crawled_links + deep_crawled_links))
            
            deep_extraction = extract_contact_data(
                book.author_name,
                book.title,
                canonical_url or (deep_candidate_urls[0] if deep_candidate_urls else ""),
                (deep_candidate_urls[0] if deep_candidate_urls else "") or page_source_url or canonical_url or "https://example.invalid/missing-source",
                merged_text,
                merged_links,
                use_ai=run_ai_extraction,
            )
            deep_extraction = _filter_extraction_urls(
                deep_extraction,
                book,
                canonical_url or (deep_candidate_urls[0] if deep_candidate_urls else ""),
            )
            deep_extraction = _drop_untrusted_extracted_contacts(
                deep_extraction,
                book,
                (deep_candidate_urls[0] if deep_candidate_urls else "") or page_source_url or canonical_url,
            )
            
            # Heal extraction
            if deep_extraction.public_email:
                extraction.public_email = deep_extraction.public_email
            if deep_extraction.public_phone:
                extraction.public_phone = deep_extraction.public_phone
            if deep_extraction.representation_email:
                extraction.representation_email = deep_extraction.representation_email
            if deep_extraction.publicist_email:
                extraction.publicist_email = deep_extraction.publicist_email
            if deep_extraction.agent_name:
                extraction.agent_name = deep_extraction.agent_name
            if deep_extraction.location:
                extraction.location = deep_extraction.location
            extraction.evidence.extend(deep_extraction.evidence)
            extraction.warnings.extend(deep_extraction.warnings)
            extraction.confidence = max(extraction.confidence, deep_extraction.confidence)


    author_bio = ""
    author_image_url = ""
    other_books = []
    
    author_profile = AuthorProfile.objects.create(
        author_name=book.author_name or "Unknown author",
        normalized_author_key=normalized_author_key(book.author_name),
        canonical_website=extraction.canonical_website or canonical_url,
        contact_page_url=extraction.contact_page_url or "",
        publisher_url="" if is_catalog_or_platform_source(extraction.publisher_url or publisher_url) else (extraction.publisher_url or publisher_url),
        instagram_url=extraction.instagram_url or socials.get("instagram_url", ""),
        facebook_url=extraction.facebook_url or socials.get("facebook_url", ""),
        tiktok_url=extraction.tiktok_url or socials.get("tiktok_url", ""),
        youtube_url=extraction.youtube_url or socials.get("youtube_url", ""),
        linkedin_url=extraction.linkedin_url or socials.get("linkedin_url", ""),
        goodreads_url=extraction.goodreads_url or socials.get("goodreads_url", ""),
        amazon_author_url=amazon_author_url,
        author_bio=author_bio,
        author_image_url=author_image_url,
        other_books=other_books,
        location=extraction.location or "",
        agent_name=extraction.agent_name or "",
        representation_email=extraction.representation_email or "",
        publicist_email=extraction.publicist_email or "",
        identity_confidence=0.85 if author_bio else (0.75 if canonical_url and book.author_name else (0.35 if book.author_name else 0.1)),
        identity_reason="Matched through public catalog and web-search evidence; manual review required by default.",
    )

    lead = Lead.objects.create(
        book=book,
        author_profile=author_profile,
        public_email=extraction.public_email or "",
        public_phone=extraction.public_phone or "",
        location=extraction.location or author_profile.location,
        representation_email=extraction.representation_email or "",
        publicist_email=extraction.publicist_email or "",
        extraction_confidence=extraction.confidence,
        manual_review_status="needs_review",
        warnings_json=extraction.warnings,
    )
    
    # Associate early discovery and scraper evidences with the newly created lead
    Evidence.objects.filter(book=book, lead__isnull=True).update(lead=lead, author_profile=author_profile)
    
    _create_evidence_for_contact(lead, author_profile, extraction, page_source_url or canonical_url, book)

    for contact in search_contact_evidence:
        field = contact["field"]
        if getattr(lead, field):
            continue
        setattr(lead, field, contact["value"])
        lead.extraction_confidence = max(lead.extraction_confidence, contact["confidence"])
        Evidence.objects.create(
            lead=lead,
            author_profile=author_profile,
            evidence_type=contact["evidence_type"],
            field_name=field,
            field_value=contact["value"],
            source_url=contact["source_url"],
            source_title=contact["source_title"][:500],
            source_snippet=contact["source_snippet"],
            confidence=contact["confidence"],
            is_primary=True,
        )
        warnings = list(lead.warnings_json or [])
        warnings.append(f"{field} came from a public search/social result snippet and needs manual verification.")
        lead.warnings_json = warnings
    lead.save(update_fields=["public_email", "public_phone", "extraction_confidence", "warnings_json", "updated_at"])

    # 4. DEEP AI RECONCILIATION & IDENTITY VERIFICATION STAGE
    gathered_contacts = {
        "public_email": lead.public_email,
        "public_phone": lead.public_phone,
        "representation_email": lead.representation_email,
        "publicist_email": lead.publicist_email,
        "instagram_url": author_profile.instagram_url,
        "facebook_url": author_profile.facebook_url,
        "tiktok_url": author_profile.tiktok_url,
        "youtube_url": author_profile.youtube_url,
        "linkedin_url": author_profile.linkedin_url,
    }
    
    # Fetch all evidence records saved for this lead
    db_evidences = list(
        Evidence.objects.filter(lead=lead).values(
            "evidence_type",
            "field_name",
            "field_value",
            "source_url",
            "source_title",
            "source_snippet",
            "confidence",
        )
    )
    
    logger.info("Executing Multi-Layered AI Review & Verification validation...")
    log_agent_thought(book.research_run, "Auditor", f"Performing name similarity and email domain validation for '{book.author_name}'...")
    if lead.public_email or lead.representation_email or lead.publicist_email:
        log_agent_thought(book.research_run, "Auditor", f"Running SMTP MX deliverability check for email '{lead.public_email or lead.representation_email or lead.publicist_email}'...")
    reconciliation = reconcile_and_verify_lead(
        book.author_name,
        book.title,
        gathered_contacts,
        db_evidences,
        use_ai=run_ai_extraction,
    )
    
    # Apply healed & verified values
    lead.public_email = reconciliation.get("verified_public_email") or ""
    lead.public_phone = reconciliation.get("verified_public_phone") or ""
    lead.representation_email = reconciliation.get("verified_representation_email") or ""
    lead.publicist_email = reconciliation.get("verified_publicist_email") or ""
    
    # Update author profile as well with the highly validated/healed contact info
    author_profile.representation_email = lead.representation_email
    author_profile.publicist_email = lead.publicist_email
    
    # Record identity verification score without letting an AI outage erase trusted deterministic evidence.
    deterministic_identity_confidence = clamp_confidence(author_profile.identity_confidence)
    reconciliation_score = clamp_confidence(reconciliation.get("identity_verification_score"))
    if reconciliation.get("is_identity_verified") or reconciliation_score >= deterministic_identity_confidence:
        author_profile.identity_confidence = max(reconciliation_score, deterministic_identity_confidence)
        author_profile.identity_reason = reconciliation.get("identity_verification_reason") or author_profile.identity_reason
    else:
        author_profile.identity_confidence = deterministic_identity_confidence
        author_profile.identity_reason = (
            f"{author_profile.identity_reason} AI reconciliation was inconclusive; kept deterministic source match."
        ).strip()
    author_profile.save()
    
    # Log reconciliation fixes into lead warnings/notes
    fixes = reconciliation.get("reconciliation_fixes") or []
    warnings = list(lead.warnings_json or [])
    for fix in fixes:
        warnings.append(f"AI Review Check: {fix}")
    if reconciliation.get("is_identity_verified") is False and author_profile.identity_confidence < 0.65:
        warnings.append("AI Review warning: identity verification score is low; verify this is the correct person manually.")
    
    # If a new contact was healed and set, add an evidence row
    for field, field_name in [("verified_public_email", "public_email"), ("verified_representation_email", "representation_email"), ("verified_publicist_email", "publicist_email")]:
        old_val = gathered_contacts.get(field_name)
        new_val = reconciliation.get(field)
        if new_val and new_val != old_val:
            Evidence.objects.create(
                lead=lead,
                author_profile=author_profile,
                evidence_type="groq_extraction",
                field_name=field_name,
                field_value=new_val,
                source_url=page_source_url or canonical_url or "https://example.invalid/healed",
                source_snippet="Healed and recovered by Multi-Layered AI Review Reconciliation.",
                confidence=reconciliation.get("identity_verification_score", 0.75),
                is_primary=True,
            )
            
    lead.warnings_json = warnings
    lead.save(update_fields=["public_email", "public_phone", "representation_email", "publicist_email", "warnings_json", "updated_at"])

    for field in [
        "canonical_website",
        "contact_page_url",
        "publisher_url",
        "instagram_url",
        "facebook_url",
        "tiktok_url",
        "youtube_url",
        "linkedin_url",
        "goodreads_url",
        "amazon_author_url",
        "author_bio",
        "location",
        "agent_name",
        "representation_email",
        "publicist_email",
    ]:
        value = getattr(author_profile, field)
        if value:
            Evidence.objects.create(
                lead=lead,
                author_profile=author_profile,
                evidence_type="social_profile" if field.endswith("_url") and "website" not in field and "publisher" not in field else "official_author_site",
                field_name=field,
                field_value=value,
                source_url=value if value.startswith("http") else (page_source_url or canonical_url or "https://example.invalid/missing-source"),
                confidence=0.65,
                is_primary=True,
            )

    _clear_unverified_lead_contacts(lead, author_profile)
    lead.refresh_from_db()
    author_profile.refresh_from_db()

    video_classifications = []
    video_reason = ""
    if run_video_search:
        log_agent_thought(book.research_run, "Harvester", f"Scanning YouTube API / video searches for book '{book.title}' promotional trailers.")
        for query in video_queries(book):
            raise_if_run_canceled(book.research_run_id)
            youtube_results = search_youtube_api(query, max_results=5)
            for dto in youtube_results:
                video_data = {
                    "book_title": book.title,
                    "author_name": book.author_name,
                    "title": dto.title,
                    "video_url": dto.url,
                    "description": dto.snippet or "",
                    "channel_name": dto.channel_name,
                    "published_at": dto.published_at,
                }
                vc = classify_video(video_data, use_ai=run_ai_extraction)
                video_classifications.append(vc)
                VideoEvidence.objects.create(
                    lead=lead,
                    video_url=dto.url,
                    title=dto.title[:500],
                    channel_name=dto.channel_name,
                    description=dto.snippet or "",
                    published_at=dto.published_at,
                    source_provider="youtube_api",
                    matches_book=vc.matches_book,
                    matches_author=vc.matches_author,
                    is_book_trailer=vc.is_book_trailer,
                    is_animated_video=vc.is_animated_video,
                    is_read_aloud=vc.is_read_aloud,
                    is_author_interview=vc.is_author_interview,
                    classification_confidence=vc.confidence,
                    classification_reason=vc.reason,
                )
                Evidence.objects.create(
                    lead=lead,
                    book=book,
                    evidence_type="youtube_result",
                    field_name="video_evidence_url",
                    field_value=dto.url,
                    source_url=dto.url,
                    source_title=dto.title[:500],
                    source_snippet=dto.snippet or "",
                    confidence=vc.confidence,
                )
            if youtube_results:
                continue
            search_query = query
            if not any(site in query for site in ["site:youtube.com", "site:vimeo.com"]):
                search_query = f'site:youtube.com OR site:vimeo.com {query}'
            log = SearchQueryLog.objects.create(
                research_run=book.research_run,
                book=book,
                query=search_query,
                provider=provider.provider_name,
            )
            results = provider.search(search_query, max_results=min(max_results, 5))
            log.result_count = len(results)
            log.save()
            for dto in results:
                if "youtube." not in dto.url.lower() and "youtu.be" not in dto.url.lower() and "vimeo." not in dto.url.lower():
                    continue
                video_data = {
                    "book_title": book.title,
                    "author_name": book.author_name,
                    "title": dto.title,
                    "video_url": dto.url,
                    "description": dto.snippet or "",
                }
                vc = classify_video(video_data, use_ai=run_ai_extraction)
                video_classifications.append(vc)
                video_reason = vc.reason
                VideoEvidence.objects.create(
                    lead=lead,
                    video_url=dto.url,
                    title=dto.title[:500],
                    description=dto.snippet or "",
                    source_provider="web_search",
                    matches_book=vc.matches_book,
                    matches_author=vc.matches_author,
                    is_book_trailer=vc.is_book_trailer,
                    is_animated_video=vc.is_animated_video,
                    is_read_aloud=vc.is_read_aloud,
                    is_author_interview=vc.is_author_interview,
                    classification_confidence=vc.confidence,
                    classification_reason=vc.reason,
                )
                Evidence.objects.create(
                    lead=lead,
                    book=book,
                    evidence_type="youtube_result" if "youtu" in dto.url.lower() else "vimeo_result",
                    field_name="video_evidence_url",
                    field_value=dto.url,
                    source_url=dto.url,
                    source_title=dto.title[:500],
                    source_snippet=dto.snippet or "",
                    confidence=vc.confidence,
                )
    lead.video_status, lead.video_confidence, status_reason = choose_video_status(video_classifications, search_completed=run_video_search)
    log_agent_thought(book.research_run, "Auditor", f"Audited {len(video_classifications)} videos. Classification: '{lead.video_status}' with confidence {lead.video_confidence:.2f}")
    log_agent_thought(book.research_run, "Harvester", f"Harvester phase completed for '{book.title}'. Scraped contacts: email={lead.public_email or 'None'}, representation_email={lead.representation_email or 'None'}")

    missing = []
    for field, value in {
        "public_email": lead.public_email,
        "public_phone": lead.public_phone,
        "canonical_website": author_profile.canonical_website,
        "amazon_book_url": book.amazon_book_url,
    }.items():
        if not value:
            missing.append(field)
    lead.missing_data_json = missing
    lead.fit_reason = "Children's or visual-book fit requires manual review against source evidence."
    payload = {
        "book": {
            "title": book.title,
            "author_name": book.author_name,
            "amazon_book_url": book.amazon_book_url,
            "asin": book.asin,
            "category": book.category,
            "publisher": book.publisher,
        },
        "author": {"author_name": author_profile.author_name, "website": author_profile.canonical_website},
        "contact": {"email": lead.public_email, "phone": lead.public_phone},
        "video_status": lead.video_status,
        "missing_data": missing,
        "warnings": lead.warnings_json,
    }
    log_agent_thought(book.research_run, "Copywriter", f"Synthesizing customized pitch angle and sales brief for '{book.title}'...")
    summary = summarize_sales_brief(payload, use_ai=run_ai_extraction)
    lead.sales_agent_summary = summary.get("sales_agent_summary", "")
    lead.fit_reason = summary.get("fit_reason", lead.fit_reason)
    lead.suggested_pitch_angle = summary.get("suggested_pitch_angle", "")
    lead.suggested_first_line = summary.get("suggested_first_line", "")
    lead.what_to_say = summary.get("what_to_say", "")
    lead.what_not_to_say = summary.get("what_not_to_say", "")
    lead.next_best_action = summary.get("next_best_action", "")
    log_agent_thought(book.research_run, "Copywriter", f"Generated customized brief & first-line pitch angle: '{lead.suggested_pitch_angle[:100]}...'")
    lead.lead_score, lead.lead_tier = score_from_lead(lead)
    verification_errors = lead_verification_errors(
        lead,
        require_amazon_url=bool(book.research_run.settings_json.get("require_amazon_url", True)),
        require_public_email=bool(book.research_run.settings_json.get("require_public_email", False)),
        include_social_only_leads=bool(book.research_run.settings_json.get("include_social_only_leads", False)),
    )
    if verification_errors:
        lead.lead_score = 0
        lead.lead_tier = "rejected"
        lead.manual_review_status = "rejected"
        warnings = list(lead.warnings_json or [])
        warnings.extend(f"Rejected by strict validation: {error}" for error in verification_errors)
        lead.warnings_json = warnings
    log_agent_thought(book.research_run, "Coordinator", f"Enforcing anti-spam validation & calculating lead score. Score: {lead.lead_score}, Tier: '{lead.lead_tier}'")
    lead.save()

    source_links = list(
        Evidence.objects.filter(lead=lead).exclude(source_url="").values_list("source_url", flat=True).distinct()
    )
    SalesAgentBrief.objects.update_or_create(
        lead=lead,
        defaults={
            "brief_markdown": render_brief_markdown(lead, source_links),
            "outreach_angle": lead.suggested_pitch_angle,
            "objection_notes": lead.what_not_to_say,
            "pitch_direct": summary.get("pitch_direct", ""),
            "pitch_agent": summary.get("pitch_agent", ""),
            "pitch_publicist": summary.get("pitch_publicist", ""),
            "source_links_json": source_links,
        },
    )
    log_agent_thought(book.research_run, "Coordinator", f"Coordinator finalized lead profile for '{book.title}' under manual review status: '{lead.manual_review_status}'.")
    return lead
