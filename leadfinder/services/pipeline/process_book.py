from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import tldextract

logger = logging.getLogger(__name__)

from django.conf import settings
from django.utils import timezone

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
from leadfinder.services.crawl.contact_form import detect_contact_forms
from leadfinder.services.crawl.contact_regex import extract_emails, extract_phones
from leadfinder.services.crawl.deobfuscate import extract_hidden_contacts
from leadfinder.services.crawl.js_render import rerender_if_thin
from leadfinder.services.crawl.safe_fetch import candidate_author_pages, discover_contact_links, safe_fetch
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
    is_corporate_author_entity,
    is_untrusted_contact_email_domain,
    looks_like_publisher_or_agency_site,
)

from leadfinder.services.scoring.lead_score import score_from_lead
from leadfinder.services.parallel import map_parallel, stage_workers
from leadfinder.services.search import get_search_provider
from leadfinder.services.search.video_provider import search_youtube_api
from leadfinder.services.social import harvest_social_profiles
from leadfinder.services.social.wikidata_profiles import find_author_profiles
from leadfinder.services.verification import verify_lead_contacts
from leadfinder.utils.normalize import normalized_author_key, is_valid_author_name, normalize_text
from leadfinder.utils.source_confidence import clamp_confidence
from leadfinder.utils.url_safety import is_safe_public_url

DOMAIN_EXTRACTOR = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


class IdentifierEvidenceUnavailableError(ValueError):
    """Raised when an ISBN/ASIN is valid syntax but has no book-level evidence."""


class CorporateEntityRejectedError(ValueError):
    """Raised when the "author" is a publisher, brand, or company.

    The pipeline only produces individual-author leads; corporate entities are
    rejected here — before classification, search waves, video lookups, and AI
    extraction — so a publisher record never spends query or token budget.
    """


def _set_processing_stage(book, stage: str, detail: str = "") -> None:
    """Persist human-readable runner progress without creating a second state model."""

    raw = dict(book.source_raw_json or {})
    raw["processing_status"] = "processing"
    raw["processing_stage"] = stage
    raw["processing_detail"] = detail
    raw["processing_updated_at"] = timezone.now().isoformat()
    book.source_raw_json = raw
    book.save(update_fields=["source_raw_json", "updated_at"])


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


ANCHOR_CONNECTORS = {"a", "an", "the", "of", "in", "on", "at", "to", "and", "or", "for", "with"}


def _title_anchor(title: str, *, max_words: int = 6) -> str:
    """Quoted-search anchor for a book title.

    Full quoted titles over-constrain web search (subtitles and long titles
    return nothing), so long titles collapse to their first few significant
    tokens, which still identify the book when paired with the author name.
    Leading/trailing connector words are dropped so the quoted anchor never
    starts or ends on filler like "of a".
    """

    words = (title or "").split()
    if len(words) <= max_words:
        return (title or "").strip()
    significant = [
        word
        for word in words
        if normalize_text(word) not in TITLE_STOPWORDS and normalize_text(word) not in ANCHOR_CONNECTORS
    ]
    anchor_words = significant[:4] if significant else words[:4]
    while anchor_words and normalize_text(anchor_words[-1]) in ANCHOR_CONNECTORS:
        anchor_words.pop()
    while anchor_words and normalize_text(anchor_words[0]) in ANCHOR_CONNECTORS:
        anchor_words.pop(0)
    return " ".join(anchor_words).strip(" :-")


def _author_query_plan(book) -> dict[str, list[str]]:
    """Categorized author-discovery queries.

    Categories exist so execution can pick a BALANCED mix: the old flat list
    put every social ``site:`` query after position 18, and the bounded query
    budget meant they were never executed at all.
    """

    author = (book.author_name or "").strip()
    title = (book.title or "").strip()
    if not author:
        return {"site": [], "contact": [], "social": []}
    anchor = _title_anchor(title)
    pair = f'"{author}" "{anchor}"' if anchor else f'"{author}"'
    social_anchor = f' "{anchor}"' if anchor else ""
    return {
        "site": [
            f"{pair} author website",
            f'"{author}" official author website',
            f"{pair} official site",
            f'"{author}" children\'s picture book author website',
            f"{pair} publisher",
            f'"{author}" author-illustrator website',
            f'"{author}" writes and illustrates',
            f"{pair} author page publisher",
        ],
        "contact": [
            f"{pair} contact",
            f'"{author}" author contact email',
            f'"{author}" school visits booking contact',
            f"{pair} media kit",
            f'"{author}" picture book author contact',
            f'"{author}" press kit author contact',
            f'"{author}" booking school visit author',
            f"{pair} get in touch",
        ],
        "social": [
            f'site:instagram.com "{author}"{social_anchor}',
            f'site:facebook.com "{author}"{social_anchor}',
            f'site:youtube.com "{author}"{social_anchor}',
            f'site:linkedin.com "{author}"{social_anchor}',
            f'site:tiktok.com "{author}"{social_anchor}',
            f'"{author}"{social_anchor} linktree OR linktr.ee OR bio.site',
            f"{pair} book trailer",
            f"{pair} interview author",
        ],
    }


def select_author_discovery_queries(book, limit: int) -> list[str]:
    """Balanced round-robin pick across query categories, capped at ``limit``.

    Guarantees the bounded budget always includes official-site, contact-intent,
    AND social-platform coverage, whatever ``limit`` is.
    """

    plan = _author_query_plan(book)
    limit = max(1, int(limit))
    ordered: list[str] = []
    categories = ["site", "contact", "social"]
    while len(ordered) < limit and any(plan[category] for category in categories):
        for category in categories:
            if plan[category]:
                ordered.append(plan[category].pop(0))
                if len(ordered) >= limit:
                    break
    return list(dict.fromkeys(ordered))[:limit]


def author_discovery_queries(book) -> list[str]:
    """Full flattened plan (all categories), kept for callers that want every
    candidate query rather than a budgeted balanced selection."""

    plan = _author_query_plan(book)
    return list(dict.fromkeys(query for category in ("site", "contact", "social") for query in plan[category]))


def deep_contact_discovery_queries(book) -> list[str]:
    author = (book.author_name or "").strip()
    anchor = _title_anchor(book.title)
    if not author:
        return []
    pair = f'"{author}" "{anchor}"' if anchor else f'"{author}"'
    return list(
        dict.fromkeys(
            [
                f'"{author}" official website',
                f'"{author}" author website contact',
                f"{pair} official website",
                f"{pair} contact email",
                f'"{author}" children\'s author contact email',
                f'"{author}" picture book author contact',
                f'"{author}" school visits booking contact',
                f'"{author}" media kit contact',
                f'"{author}" email "@gmail.com" OR "@yahoo.com" OR "@outlook.com"',
                f'"{author}" ("agent" OR "agency" OR "represented by") contact',
                f'"{author}" ("publicist" OR "publicity" OR "press" OR "media") email',
                f'"{author}" contact page',
                f'site:linktr.ee OR site:bio.site OR site:carrd.co OR site:beacons.ai "{author}"',
                f'site:substack.com "{author}" children book',
                f'"{author}" ("media kit" OR "press kit") author',
                f'"{author}" author ("email me" OR "reach me" OR "get in touch")',
                f'"{author}" illustrator author contact booking',
                f"{pair} author visit booking",
            ]
        )
    )


def _placeholder_book_title(title: str | None, asin: str | None = None) -> bool:
    normalized = normalize_text(title)
    code = normalize_text(asin)
    return (
        not normalized
        or normalized in {"missing", "unknown"}
        or normalized.startswith("book for asin")
        or normalized.startswith("book for isbn")
        or bool(code and normalized == code)
    )


def _metadata_recovery_queries(book) -> list[str]:
    title = (book.title or "").strip()
    asin = (book.asin or "").strip()
    queries: list[str] = []
    if title and not _placeholder_book_title(title, asin):
        queries.extend(
            [
                f'"{title}" author',
                f'"{title}" "by"',
            ]
        )
        if asin:
            queries.append(f'"{asin}" "{title}"')
    if asin:
        queries.append(f'"{asin}" author')
    return list(dict.fromkeys(queries))


def _metadata_result_matches_book(dto, book) -> bool:
    text = f"{getattr(dto, 'title', '')} {getattr(dto, 'snippet', '')} {getattr(dto, 'url', '')}"
    normalized_text = normalize_text(text)
    asin = (book.asin or "").strip().lower()
    if asin and asin in text.lower():
        return True
    if _placeholder_book_title(book.title, book.asin):
        return False
    tokens = _title_tokens(book.title)
    if not tokens:
        return False
    matches = sum(1 for token in tokens if token in normalized_text)
    required = min(3, max(1, len(tokens)))
    return matches >= required


def _candidate_author_looks_like_title_fragment(candidate: str | None, title: str | None) -> bool:
    candidate_tokens = [
        token
        for token in normalize_text(candidate).split()
        if len(token) >= 3 and token not in NAME_STOPWORDS
    ]
    if not candidate_tokens:
        return True
    title_terms = set(normalize_text(title).split())
    return all(token in title_terms for token in candidate_tokens)


def _recover_missing_author_from_search(book, provider, max_results: int) -> bool:
    """Recover a blank author from source-backed title/identifier search results.

    Contact discovery intentionally requires an author name. Manual ASIN/ISBN
    runs can start with only an identifier and title, so this bridge records a
    bounded metadata search before the main author/contact workflow.
    """
    if book.author_name and is_valid_author_name(book.author_name):
        return False

    queries = _metadata_recovery_queries(book)
    if not queries:
        log_agent_thought(
            book.research_run,
            "Harvester",
            f"Author metadata recovery skipped for '{book.title}' because no title or identifier evidence was available.",
        )
        return False

    from leadfinder.services.amazon.amazon_scraper import extract_metadata_from_results

    log_agent_thought(
        book.research_run,
        "Harvester",
        f"Author missing for '{book.title}'. Running title/identifier metadata recovery before contact search.",
    )
    planned_queries = queries[:4]

    def _run_recovery_query(query):
        """Network-only worker; query logging and extraction stay serial."""
        try:
            return query, provider.search(query, max_results=max_results), None
        except Exception as exc:
            return query, [], exc

    # The bounded metadata queries are independent network waits — run them
    # concurrently, then process in query order so the highest-priority query
    # still wins the recovery.
    recovery_batch = map_parallel(_run_recovery_query, planned_queries)

    for query, results, search_error in recovery_batch:
        raise_if_run_canceled(book.research_run_id)
        log = SearchQueryLog.objects.create(
            research_run=book.research_run,
            book=book,
            query=query,
            provider=provider.provider_name,
        )
        if search_error is None:
            log.result_count = len(results)
            log.status = "success"
        else:
            results = []
            log.status = "failed"
            log.error_message = str(search_error)
        log.save()

        matching_results = []
        for dto in results:
            result_class, confidence = classify_result_url(dto.url)
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
            if _metadata_result_matches_book(dto, book):
                matching_results.append(dto)

        extracted = extract_metadata_from_results(matching_results, book.asin, book.title)
        authors = extracted.get("authors") or []
        first_author = authors[0] if authors else {}
        recovered_author = first_author.get("name") if isinstance(first_author, dict) else ""
        if _candidate_author_looks_like_title_fragment(recovered_author, book.title):
            continue
        if recovered_author and is_valid_author_name(recovered_author):
            previous_raw = dict(book.source_raw_json or {})
            previous_raw.setdefault("metadata_recovery", {})
            previous_raw["metadata_recovery"].update(
                {
                    "method": "title_identifier_search",
                    "query": query,
                    "source_url": matching_results[0].url if matching_results else "",
                    "source_title": matching_results[0].title if matching_results else "",
                }
            )
            if extracted.get("title") and _placeholder_book_title(book.title, book.asin):
                book.title = extracted["title"][:500]
            book.author_name = recovered_author[:255]
            book.book_data_confidence = max(float(book.book_data_confidence or 0), 0.72)
            book.source_raw_json = previous_raw
            book.save(update_fields=["title", "author_name", "book_data_confidence", "source_raw_json", "updated_at"])
            Evidence.objects.create(
                book=book,
                evidence_type="web_search_result",
                field_name="author_name",
                field_value=book.author_name,
                source_url=matching_results[0].url if matching_results else book.amazon_source_url or book.amazon_book_url,
                source_title=(matching_results[0].title if matching_results else "Metadata recovery")[:500],
                source_snippet=(matching_results[0].snippet if matching_results else "")[:500],
                confidence=0.72,
                is_primary=True,
            )
            log_agent_thought(
                book.research_run,
                "Harvester",
                f"Recovered author '{book.author_name}' for '{book.title}' from title/identifier metadata evidence.",
            )
            return True

    log_agent_thought(
        book.research_run,
        "Harvester",
        f"Author metadata recovery found no source-backed author for '{book.title}'. Contact search will remain limited.",
    )
    return False


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


def _merge_wikidata_profiles(book, profiles: dict, candidate_urls: list[str], socials: dict[str, str]) -> None:
    """Fold free Wikidata author profiles into discovery evidence (main thread only).

    Identity was already verified by the Wikidata entity-label match, so opaque
    handles (YouTube channel IDs, Goodreads numeric IDs) are trusted here; the
    Wikidata entity URL is stored as the auditable source for every value.
    """
    if float(profiles.get("confidence") or 0) < 0.6:
        return
    entity_url = profiles.get("entity_url") or "https://www.wikidata.org"
    label = str(profiles.get("entity_label") or "")
    website = str(profiles.get("canonical_website") or "")
    if website and is_safe_public_url(website) and not _domain_is_retail_or_social(website):
        candidate_urls.append(website)
        Evidence.objects.create(
            book=book,
            evidence_type="official_author_site",
            field_name="wikidata_official_website",
            field_value=website,
            source_url=entity_url,
            source_title=f"Wikidata: {label}"[:500],
            confidence=float(profiles.get("confidence") or 0.65),
        )
    for field in ("instagram_url", "facebook_url", "tiktok_url", "linkedin_url", "youtube_url", "goodreads_url"):
        url = str(profiles.get(field) or "")
        if not url or field in socials:
            continue
        socials[field] = url
        Evidence.objects.create(
            book=book,
            evidence_type="social_profile",
            field_name=field,
            field_value=url,
            source_url=entity_url,
            source_title=f"Wikidata: {label}"[:500],
            confidence=0.6,
        )
    wikipedia_url = str(profiles.get("wikipedia_url") or "")
    if wikipedia_url:
        Evidence.objects.create(
            book=book,
            evidence_type="web_search_result",
            field_name="wikipedia_url",
            field_value=wikipedia_url,
            source_url=wikipedia_url,
            source_title=f"Wikipedia: {label}"[:500],
            confidence=0.55,
        )


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


def _fetch_with_js_fallback(url):
    """safe_fetch + opt-in headless re-render for thin JS-built pages."""

    return rerender_if_thin(safe_fetch(url))


def _collect_hidden_page_contacts(fetched, book, search_contact_evidence: list[dict]) -> None:
    """Recover contacts hidden in raw HTML and record on-site contact forms.

    Plain visible-text extraction misses mailto:/tel: links, Cloudflare
    data-cfemail payloads, JSON-LD email fields, and ``name [at] domain [dot]
    com`` prose.  Pages reaching this helper are already identity-trusted
    author sites, so recovered values keep the standard trust checks but earn
    contact_page confidence.  Contact forms are stored as Evidence so a lead
    keeps an actionable route even when no email/phone is published.
    """

    title = extract_page_title(fetched.html)
    hidden_emails, hidden_phones = extract_hidden_contacts(fetched.html)
    for email in hidden_emails:
        if not _email_matches_author_or_trusted_source(email, book, fetched.url, trusted_source=True):
            continue
        search_contact_evidence.append(
            {
                "field": "public_email",
                "value": email,
                "source_url": fetched.url,
                "source_title": title,
                "source_snippet": "Recovered from mailto:/obfuscated markup on the author's own site.",
                "evidence_type": "contact_page",
                "confidence": 0.7,
            }
        )
    for phone in hidden_phones:
        search_contact_evidence.append(
            {
                "field": "public_phone",
                "value": phone,
                "source_url": fetched.url,
                "source_title": title,
                "source_snippet": "Recovered from tel:/obfuscated markup on the author's own site.",
                "evidence_type": "contact_page",
                "confidence": 0.66,
            }
        )
    for form in detect_contact_forms(fetched.html, fetched.url):
        Evidence.objects.create(
            book=book,
            evidence_type="contact_page",
            field_name="contact_form_url",
            field_value=form["url"],
            source_url=fetched.url,
            source_title=title[:500],
            source_snippet=f"On-site {form['kind']} detected (fields: {', '.join(form['fields'][:5])}).",
            confidence=0.65 if form["kind"] == "contact_form" else 0.5,
        )


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


def process_book(
    book,
    run_video_search: bool = True,
    run_ai_extraction: bool = True,
    verify_email_mx: bool = True,
) -> Lead:
    raise_if_run_canceled(book.research_run_id)
    _set_processing_stage(book, "Resolving exact book evidence", "Checking the identifier against permitted public sources.")
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

                if not am_res or not am_res.get("authors") or not am_res.get("description") or am_res.get("rating") is None:
                    log_agent_thought(
                        book.research_run,
                        "Harvester",
                        f"Public catalogs were incomplete or missing fields for {book.asin}; checking search engine evidence.",
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

    # ASINs are syntax-only identifiers.  Never infer a book or author from a
    # generic marketplace/search page: without a resolved title and author,
    # proceeding would turn unrelated sites and social profiles into a lead.
    from leadfinder.services.amazon.amazon_url_parser import extract_asin

    has_exact_supplied_product_url = extract_asin(book.amazon_book_url or "") == (book.asin or "").upper()
    if (
        book.source_provider == "manual"
        and book.asin
        and (
            (not book.author_name and not has_exact_supplied_product_url)
            or not book.title
            or re.fullmatch(r"\s*Book for (?:ASIN|ISBN10|ISBN13) [A-Z0-9-]+\s*", book.title, re.I)
        )
    ):
        _set_processing_stage(
            book,
            "Exact book evidence not found",
            "No matching public catalog or indexed book result confirmed this identifier.",
        )
        raise IdentifierEvidenceUnavailableError(
            f"No exact public book metadata was found for {book.asin}. "
            "The item was not enriched to prevent a mismatched author or contact."
        )

    _set_processing_stage(book, "Finding author-owned sources", "Looking for identity-matched official sites and public profiles.")
    enrichment_provider = (book.research_run.settings_json or {}).get("enrichment_provider")
    provider = get_search_provider(enrichment_provider or book.research_run.source_provider)
    max_results = min(max(int(getattr(settings, "APP_MAX_SEARCH_RESULTS_PER_QUERY", 5)), 1), 10)
    if not book.author_name:
        _recover_missing_author_from_search(book, provider, max_results)

    # AUTHOR-ONLY GATE: reject publishers, brands, and corporate "authors"
    # immediately.  This runs before book classification, every search wave,
    # video lookup, and AI extraction so a company record spends zero query
    # or token budget.
    if book.author_name and is_corporate_author_entity(book.author_name):
        _set_processing_stage(
            book,
            "Rejected: publisher or company",
            f"'{book.author_name}' is a corporate entity, not an individual author.",
        )
        log_agent_thought(
            book.research_run,
            "Auditor",
            f"Rejected '{book.author_name}' for '{book.title}': publisher/company entity — author-only pipeline.",
        )
        raise CorporateEntityRejectedError(
            f"'{book.author_name}' is a publisher or company, not an individual author. Only author leads are kept."
        )

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

    def _has_trusted_search_contact() -> bool:
        return any(
            contact.get("evidence_type") == "contact_page" and contact.get("confidence", 0) >= 0.65
            for contact in search_contact_evidence
        )

    def _discovery_satisfied() -> bool:
        """Enough evidence to stop spending search budget: an official site
        plus either a trusted contact hit or real social presence."""

        return bool(candidate_urls) and (_has_trusted_search_contact() or len(socials) >= 2)

    # Wave 1 is a balanced site/contact/social mix. Wave 2 fires ONLY when
    # wave 1 left gaps, so easy authors stop costing the full query budget
    # while hard ones still get the remaining planned queries.
    wave_one_limit = max(3, (2 * max_author_queries) // 3)
    wave_one_queries = select_author_discovery_queries(book, wave_one_limit)
    wave_two_pool = [query for query in author_discovery_queries(book) if query not in set(wave_one_queries)]
    wikidata_enabled = bool(getattr(settings, "APP_WIKIDATA_AUTHOR_LOOKUP", True)) and bool(book.author_name)

    def _run_discovery_task(task):
        """Network-only worker: one search query or the Wikidata author lookup."""
        kind, payload = task
        try:
            if kind == "wikidata":
                return kind, payload, find_author_profiles(book.author_name), None
            return kind, payload, provider.search(payload, max_results=max_results), None
        except Exception as exc:
            return kind, payload, None, exc

    def _run_search_wave(queries: list[str], *, include_wikidata: bool = False) -> None:
        nonlocal publisher_url
        # One tagged task list: the free Wikidata author lookup overlaps with
        # the search queries in the same bounded pool instead of a serial step.
        tasks: list[tuple[str, str]] = [("search", query) for query in queries]
        if include_wikidata and wikidata_enabled:
            tasks.insert(0, ("wikidata", ""))
        for kind, payload, task_result, task_error in map_parallel(_run_discovery_task, tasks):
            raise_if_run_canceled(book.research_run_id)
            if kind == "wikidata":
                if task_error is None and task_result:
                    _merge_wikidata_profiles(book, task_result, candidate_urls, socials)
                continue
            query = payload
            results = task_result if task_error is None else []
            search_error = task_error
            log = SearchQueryLog.objects.create(research_run=book.research_run, book=book, query=query, provider=provider.provider_name)
            if search_error is None:
                log.result_count = len(results)
                log.status = "success"
            else:
                results = []
                log.status = "failed"
                log.error_message = str(search_error)
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

    _run_search_wave(wave_one_queries, include_wikidata=True)
    if not _discovery_satisfied() and wave_two_pool:
        wave_two_limit = min(len(wave_two_pool), max_author_queries - wave_one_limit + max(2, max_author_queries // 3))
        if wave_two_limit > 0:
            log_agent_thought(
                book.research_run,
                "Harvester",
                f"First search wave left gaps for '{book.author_name}'; running {wave_two_limit} follow-up queries.",
            )
            _run_search_wave(wave_two_pool[:wave_two_limit])

    candidate_urls = list(dict.fromkeys(candidate_urls))
    canonical_url = candidate_urls[0] if candidate_urls else ""
    crawled_text = ""
    crawled_links: list[str] = []
    page_source_url = canonical_url
    if canonical_url:
        _set_processing_stage(book, "Reviewing author website", "Collecting public contact evidence from permitted author-owned pages.")
        log_agent_thought(book.research_run, "Harvester", f"Crawling author website {canonical_url} to extract contact links and page content.")
        max_pages = int(getattr(settings, "APP_MAX_AUTHOR_PAGES_TO_CRAWL", 5))
        first_hop_urls = candidate_author_pages(canonical_url)[:max_pages]
        crawled_pages = [
            page for page in map_parallel(_fetch_with_js_fallback, first_hop_urls)
            if page and page.status_code < 400
        ]

        # Second hop: follow contact-intent links discovered ON the author's
        # own pages.  The fixed path list cannot know custom slugs such as
        # /visit-me or /booking-info, so the crawl reads the site's own
        # navigation one bounded hop deeper on the same identity-trusted host.
        second_hop_budget = max(0, min(int(getattr(settings, "APP_MAX_SECOND_HOP_PAGES", 4)), 10))
        if second_hop_budget and crawled_pages:
            seen_urls = {page.url.rstrip("/") for page in crawled_pages}
            seen_urls.update(url.rstrip("/") for url in first_hop_urls)
            discovered_urls: list[str] = []
            for page in crawled_pages:
                for link in discover_contact_links(page.html, page.url):
                    if link.rstrip("/") in seen_urls:
                        continue
                    seen_urls.add(link.rstrip("/"))
                    discovered_urls.append(link)
                    if len(discovered_urls) >= second_hop_budget:
                        break
                if len(discovered_urls) >= second_hop_budget:
                    break
            if discovered_urls:
                log_agent_thought(
                    book.research_run,
                    "Harvester",
                    f"Following {len(discovered_urls)} contact-intent links one hop deeper inside {(urlparse(canonical_url).hostname or '')}.",
                )
                crawled_pages.extend(
                    page for page in map_parallel(_fetch_with_js_fallback, discovered_urls)
                    if page and page.status_code < 400
                )

        for fetched in crawled_pages:
            page_source_url = fetched.url
            title = extract_page_title(fetched.html)
            text = extract_visible_text(fetched.html)
            links = extract_links(fetched.html, fetched.url)
            crawled_text = f"{crawled_text}\n{text}"[: int(getattr(settings, "APP_MAX_GROQ_INPUT_CHARS", 12000))]
            crawled_links.extend(link for link in links if link not in crawled_links)
            _collect_hidden_page_contacts(fetched, book, search_contact_evidence)
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
    if not extraction.public_email and not extraction.representation_email and not _has_trusted_search_contact():
        logger.info(f"Initiating multi-layered Deep Search for author {book.author_name}...")
        log_agent_thought(book.research_run, "Harvester", f"Deep searching additional contact sources for '{book.author_name}'...")
        deep_candidate_urls = []
        deep_crawled_text = ""
        deep_crawled_links = []
        max_deep_queries = min(
            max(int(getattr(settings, "APP_MAX_DEEP_CONTACT_QUERIES", 5)), 1),
            len(deep_contact_discovery_queries(book)),
        )

        deep_queries = deep_contact_discovery_queries(book)[:max_deep_queries]

        def _run_deep_query(query):
            try:
                return provider.search(query, max_results=max_results), None
            except Exception as exc:
                return [], exc

        def _deep_search_satisfied() -> bool:
            return _has_trusted_search_contact() or len(deep_candidate_urls) >= int(
                getattr(settings, "APP_MAX_AUTHOR_PAGES_TO_CRAWL", 3)
            )

        # Fire deep queries in small waves instead of one big batch: the old
        # loop spent the whole deep budget upfront, then broke early — the
        # network cost was already paid. Waves stop paying once a trusted
        # contact or enough new author pages turn up.
        deep_wave_size = 3
        for wave_start in range(0, len(deep_queries), deep_wave_size):
            wave_queries = deep_queries[wave_start : wave_start + deep_wave_size]
            deep_batch = map_parallel(_run_deep_query, wave_queries)
            for query, (results, search_error) in zip(wave_queries, deep_batch):
                raise_if_run_canceled(book.research_run_id)
                log = SearchQueryLog.objects.create(research_run=book.research_run, book=book, query=query, provider=provider.provider_name)
                if search_error is None:
                    log.result_count = len(results)
                    log.status = "success"
                else:
                    results = []
                    log.status = "failed"
                    log.error_message = str(search_error)
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
            if _deep_search_satisfied():
                break

        deep_candidate_urls = list(dict.fromkeys(deep_candidate_urls))
        # If we found any new candidate pages in deep search, crawl them to find contact email/phone.
        if deep_candidate_urls:
            max_pages = int(getattr(settings, "APP_MAX_AUTHOR_PAGES_TO_CRAWL", 3))
            deep_pages = [url for url in deep_candidate_urls[:max_pages] if url != canonical_url]
            deep_fetched_pages = [
                page for page in map_parallel(_fetch_with_js_fallback, deep_pages)
                if page and page.status_code < 400
            ]
            # Second hop on deep-search sites too: contact-intent links found
            # on these identity-trusted pages get one bounded follow.
            second_hop_budget = max(0, min(int(getattr(settings, "APP_MAX_SECOND_HOP_PAGES", 4)), 10))
            if second_hop_budget and deep_fetched_pages:
                seen_urls = {page.url.rstrip("/") for page in deep_fetched_pages}
                seen_urls.update(url.rstrip("/") for url in deep_pages)
                seen_urls.add(canonical_url.rstrip("/"))
                discovered_urls: list[str] = []
                for page in deep_fetched_pages:
                    for link in discover_contact_links(page.html, page.url):
                        if link.rstrip("/") in seen_urls:
                            continue
                        seen_urls.add(link.rstrip("/"))
                        discovered_urls.append(link)
                        if len(discovered_urls) >= second_hop_budget:
                            break
                    if len(discovered_urls) >= second_hop_budget:
                        break
                if discovered_urls:
                    deep_fetched_pages.extend(
                        page for page in map_parallel(_fetch_with_js_fallback, discovered_urls)
                        if page and page.status_code < 400
                    )
            for fetched in deep_fetched_pages:
                title = extract_page_title(fetched.html)
                text = extract_visible_text(fetched.html)
                links = extract_links(fetched.html, fetched.url)
                deep_crawled_text = f"{deep_crawled_text}\n{text}"[:3000]
                deep_crawled_links.extend(link for link in links if link not in deep_crawled_links)
                _collect_hidden_page_contacts(fetched, book, search_contact_evidence)
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


    metadata_recovered_author = bool((book.source_raw_json or {}).get("metadata_recovery") and book.author_name)
    # NOTE: bio/image data is not collected yet, so it must not feed confidence.
    # Corporate entities are already rejected by the early author-only gate;
    # if one ever slips through, it must never earn a confidence boost here.
    initial_identity_confidence = (
        0.75 if canonical_url and book.author_name else (0.55 if metadata_recovered_author else (0.35 if book.author_name else 0.1))
    )
    identity_reason_text = (
        "Author recovered from title/identifier search evidence; official contact path still requires manual review."
        if metadata_recovered_author
        else "Matched through public catalog and web-search evidence; manual review required by default."
    )
    # Reuse an existing profile for the same author across runs/books instead
    # of accumulating one duplicate profile per processed book.
    profile_field_values = {
        "canonical_website": extraction.canonical_website or canonical_url,
        "contact_page_url": extraction.contact_page_url or "",
        "publisher_url": "" if is_catalog_or_platform_source(extraction.publisher_url or publisher_url) else (extraction.publisher_url or publisher_url),
        "instagram_url": extraction.instagram_url or socials.get("instagram_url", ""),
        "facebook_url": extraction.facebook_url or socials.get("facebook_url", ""),
        "tiktok_url": extraction.tiktok_url or socials.get("tiktok_url", ""),
        "youtube_url": extraction.youtube_url or socials.get("youtube_url", ""),
        "linkedin_url": extraction.linkedin_url or socials.get("linkedin_url", ""),
        "goodreads_url": extraction.goodreads_url or socials.get("goodreads_url", ""),
        "amazon_author_url": amazon_author_url,
        "location": extraction.location or "",
        "agent_name": extraction.agent_name or "",
        "representation_email": extraction.representation_email or "",
        "publicist_email": extraction.publicist_email or "",
    }
    author_key = normalized_author_key(book.author_name)
    try:
        author_profile, profile_created = AuthorProfile.objects.get_or_create(
            normalized_author_key=author_key,
            defaults={
                "author_name": book.author_name or "Unknown author",
                **profile_field_values,
                "identity_confidence": initial_identity_confidence,
                "identity_reason": identity_reason_text,
            },
        )
    except AuthorProfile.MultipleObjectsReturned:
        # Legacy databases can already hold duplicate keys; reuse the oldest.
        author_profile = AuthorProfile.objects.filter(normalized_author_key=author_key).order_by("created_at").first()
        profile_created = False
    if not profile_created:
        # Enrich the shared profile: fill blanks, never overwrite sourced data.
        profile_updates = {
            field: value
            for field, value in profile_field_values.items()
            if value and not getattr(author_profile, field)
        }
        if initial_identity_confidence > (author_profile.identity_confidence or 0):
            profile_updates["identity_confidence"] = initial_identity_confidence
            profile_updates["identity_reason"] = identity_reason_text
        if profile_updates:
            for field, value in profile_updates.items():
                setattr(author_profile, field, value)
            author_profile.save(update_fields=[*profile_updates, "updated_at"])


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

    # Start the video search NOW: its queries only need the book title/author,
    # so the network wait overlaps social-profile auditing and contact
    # verification instead of adding a serial stage at the end of the book.
    video_classifications = []
    video_reason = ""
    video_pool = None
    video_futures: list = []
    if run_video_search:
        _set_processing_stage(book, "Checking existing video presence", "Looking for public trailer and promotional-video evidence.")
        log_agent_thought(book.research_run, "Harvester", f"Scanning YouTube API / video searches for book '{book.title}' promotional trailers.")

        def _run_video_query(query):
            """Network-only worker: YouTube API, then web-search fallback, then classify."""
            entries = []
            try:
                youtube_results = search_youtube_api(query, max_results=5)
            except Exception:
                youtube_results = []
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
                entries.append(("youtube_api", dto, vc))
            if entries:
                return (entries, None, 0, None)

            search_query = query
            if not any(site in query for site in ["site:youtube.com", "site:vimeo.com"]):
                search_query = f'site:youtube.com OR site:vimeo.com {query}'
            try:
                results = provider.search(search_query, max_results=min(max_results, 5))
                search_error = None
            except Exception as exc:
                results = []
                search_error = exc
            for dto in results:
                lower_url = dto.url.lower()
                if "youtube." not in lower_url and "youtu.be" not in lower_url and "vimeo." not in lower_url:
                    continue
                video_data = {
                    "book_title": book.title,
                    "author_name": book.author_name,
                    "title": dto.title,
                    "video_url": dto.url,
                    "description": dto.snippet or "",
                }
                vc = classify_video(video_data, use_ai=run_ai_extraction)
                entries.append(("web_search", dto, vc))
            return (entries, search_query, len(results), search_error)

        video_pool = ThreadPoolExecutor(max_workers=stage_workers(), thread_name_prefix="video")
        video_futures = [video_pool.submit(_run_video_query, query) for query in video_queries(book)]

    try:
        _set_processing_stage(book, "Auditing public social profiles", "Only identity-matched public profiles and one-hop bio links are considered.")
        social_audits = harvest_social_profiles(lead)
        if social_audits:
            fetched_socials = sum(1 for audit in social_audits if audit.fetch_status == "fetched")
            log_agent_thought(
                book.research_run,
                "Harvester",
                f"Inspected {len(social_audits)} public social profiles; {fetched_socials} were accessible.",
            )

        _clear_unverified_lead_contacts(lead, author_profile)
        lead.refresh_from_db()
        author_profile.refresh_from_db()

        _set_processing_stage(book, "Verifying contact evidence", "Checking source quality and selected contact signals.")
        verify_lead_contacts(lead, check_network=verify_email_mx)
        lead.refresh_from_db()
        log_agent_thought(
            book.research_run,
            "Auditor",
            f"Contact verification: {lead.verification_status} ({lead.verification_score}/100).",
        )
        video_batch = [future.result() for future in video_futures]
    finally:
        if video_pool is not None:
            video_pool.shutdown(wait=True)

    for entries, search_query, result_count, search_error in video_batch:
        raise_if_run_canceled(book.research_run_id)
        if search_query is not None:
            log = SearchQueryLog.objects.create(
                research_run=book.research_run,
                book=book,
                query=search_query,
                provider=provider.provider_name,
            )
            log.result_count = result_count
            if search_error is not None:
                log.status = "failed"
                log.error_message = str(search_error)
            log.save()
        for source, dto, vc in entries:
            video_classifications.append(vc)
            if source == "web_search":
                video_reason = vc.reason
            VideoEvidence.objects.create(
                lead=lead,
                video_url=dto.url,
                title=dto.title[:500],
                channel_name=getattr(dto, "channel_name", "") or "",
                description=dto.snippet or "",
                published_at=getattr(dto, "published_at", "") or "",
                source_provider=source,
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
                evidence_type="vimeo_result" if (source == "web_search" and "vimeo" in dto.url.lower()) else "youtube_result",
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
    _set_processing_stage(book, "Preparing the review brief", "Creating the evidence-backed sales summary and quality score.")
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

    if lead.lead_tier == "hot":
        from leadfinder.services.notify import notify_hot_lead

        notify_hot_lead(lead)

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
