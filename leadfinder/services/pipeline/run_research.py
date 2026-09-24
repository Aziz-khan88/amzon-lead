from __future__ import annotations

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings
from django.db import close_old_connections, connection
from django.db.models import Q

from leadfinder.models import Book, Evidence, ResearchRun, SearchQueryLog, SearchResult, AgentThought
from leadfinder.services.amazon.amazon_url_parser import (
    classify_amazon_search_result,
    extract_asin,
    is_amazon_url,
    normalize_amazon_book_url,
)
from leadfinder.services.books.google_books_provider import GoogleBooksProvider
from leadfinder.services.discovery.site_providers import SITE_DISCOVERY_PROVIDERS

def log_agent_thought(run, agent_name: str, message: str) -> None:
    try:
        AgentThought.objects.create(research_run=run, agent_name=agent_name, message=message)
    except Exception:
        pass

from leadfinder.services.pipeline.dedupe import dedupe_book_candidates
from leadfinder.services.pipeline.cancellation import RunCanceled, raise_if_run_canceled
from leadfinder.services.pipeline.process_book import process_book
from leadfinder.services.pipeline.source_audit import is_corporate_author_entity
from leadfinder.services.parallel import map_parallel
from leadfinder.services.search import get_search_provider
from leadfinder.utils.normalize import (
    clean_title_from_search,
    normalized_book_key,
    clean_author_name,
    extract_authors_from_colon_format,
    is_valid_author_name,
)

PROFESSIONAL_KEYWORD_SUGGESTIONS = [
    "new children picture book author contact",
    "self published children's picture book author",
    "indie children book author school visits",
    "picture book author media kit contact",
    "children author booking email",
    "children's book author visit contact",
    "kids bedtime story author amazon",
    "new children's book launch author",
    "children book illustrator author contact",
    "social emotional learning picture book author",
    "rhyming children's book author",
    "faith based children's book author contact",
    "children's picture book independently published",
    "KDP children's picture book",
    "children's book about kindness independently published",
    "friendship picture book for kids independently published",
    "children's picture book self esteem",
    "children's book about bullying independently published",
    "children's book author podcast interview",
    "picture book author classroom visit contact",
]


def keyword_suggestions() -> list[str]:
    return PROFESSIONAL_KEYWORD_SUGGESTIONS.copy()


def _is_generic_illustration_query(lower: str) -> bool:
    generic_illustration = {
        "illustration", "illustrations", "illustrator", "illustrators",
        "children illustration", "children's illustration",
        "children illustrator", "children's illustrator",
        "children book illustration", "children books illustration",
        "children's book illustration", "children's books illustration",
        "children book illustrator", "children books illustrator",
        "children's book illustrator", "children's books illustrator",
        "kids illustration", "kids illustrator",
        "kids book illustration", "kids books illustration",
        "kids book illustrator", "kids books illustrator",
    }
    if lower in generic_illustration:
        return True
    has_child_term = any(term in lower for term in ["children", "childrens", "children's", "kids", "kid"])
    has_illustration_term = any(term in lower for term in ["illustration", "illustrator", "illustrated"])
    return has_child_term and has_illustration_term


def _is_generic_children_query(lower: str) -> bool:
    generic_children = {
        "children", "children's", "children book", "children's book", "children books", "children's books",
        "kids", "kids book", "kids books", "picture book", "picture books"
    }
    return lower in generic_children


def _keyword_variants(keyword: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", (keyword or "").strip().strip('"')).strip()
    variants: list[str] = []
    lower = cleaned.lower()
    if _is_generic_illustration_query(lower):
        variants.extend([
            "children picture book illustrator",
            "children book illustrator",
            "children picture book author illustrator",
            "illustrated children picture book",
            "kids picture book illustrator",
            "self published children book illustrator",
            "children illustrator author contact",
            "picture book illustrator school visits",
        ])
    if _is_generic_children_query(lower):
        variants.extend([
            "children picture book",
            "kids picture book",
            "new children picture book author",
            "self published children's picture book",
            "indie children book author",
            "children author school visits",
            "picture book author media kit",
            "children book launch author",
        ])
    if cleaned:
        variants.append(cleaned)
    singular = re.sub(r"\bbooks\b", "book", cleaned, flags=re.I)
    if singular and singular.lower() != cleaned.lower():
        variants.append(singular)
    return list(dict.fromkeys(variant for variant in variants if variant))


def discovery_queries(keyword: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", (keyword or "").strip().strip('"')).strip()
    lower = cleaned.lower()

    is_generic = _is_generic_illustration_query(lower) or _is_generic_children_query(lower)
    
    queries: list[str] = []
    if is_generic:
        patterns = [
            "amazon.com/dp {term} by",
            'site:amazon.com "{term}" "by"',
            'site:amazon.com/dp "{term}"',
            "amazon.com {term} paperback author",
            'site:amazon.com "{term}" "picture book"',
            'site:amazon.com "{term}" "kids book"',
            'amazon "{term}" "children\'s book" "by"',
            '"{term}" "amazon.com/dp"',
            '"{term}" "Kindle edition" "by"',
            '"{term}" "paperback" "by" "Amazon.com"',
            '"{term}" "buy on Amazon" "author"',
            '"{term}" "new release" "children\'s book"',
            '"{term}" "school visits" "Amazon"',
            'site:amazon.com/dp "Independently published" "{term}"',
            'site:amazon.com/dp "Reading age" "3 - 8 years" "Independently published"',
            'site:amazon.com/dp "Paperback" "{term}" "Independently published"',
        ]
    else:
        patterns = [
            'site:amazon.com "{term}"',
            'amazon "{term}"',
            '"{term}" "amazon.com/dp"',
            '{term}',
        ]
        
    variants = _keyword_variants(keyword)
    # Round-robin pattern-major across variants: a bounded query budget then
    # covers EVERY variant with the highest-yield patterns first, instead of
    # spending the whole budget exhausting patterns for the first variant
    # (variant-major order never reached later variants under the cap).
    for pattern in patterns:
        for term in variants:
            queries.append(pattern.format(term=term))
    return list(dict.fromkeys(queries))


EXCLUDED_WORDS = {
    "step", "techniques", "illustration", "illustrations", "illustrator", "illustrators",
    "design", "storytelling", "visual", "creative", "guide", "masters", "book", "books",
    "paperback", "hardcover", "edition", "ages", "years", "amazon", "stars", "rating", "review",
    "reviews", "publisher", "published", "today", "scholastic", "instructor", "presentations",
    "empower", "perfection", "robot", "island", "introduction", "foreword", "contributor",
    "editor", "reader", "series", "volume", "vol", "illustrated", "writing", "write", "how",
    "to", "the", "art", "of", "picture", "pictures", "perfect", "successful", "successfully",
    "sells", "publishers", "readers", "classic", "stories", "treasury", "treasuries", "complete",
    "guide", "learning", "learn", "draw", "drawing", "paint", "painting"
}


def guess_title_author(title: str, snippet: str | None) -> tuple[str, str, float]:
    cleaned_title = clean_title_from_search(title)
    snippet_text = snippet or ""
    
    author = ""
    confidence = 0.35
    
    # 0. Check colon/comma format first! E.g. "Brave Every Day: Ludwig, Trudy, Barton, Patrice: 9780593306376 ..."
    colon_authors = extract_authors_from_colon_format(title)
    if colon_authors:
        author = colon_authors[0]
        confidence = 0.75

    # 1. Search for strong Amazon/book author pattern with label first: e.g. "by Jill Bossert (Author)"
    if not author:
        strong_pattern = r"\bby\s+([A-Z][A-Za-z .'-]{1,40})\s*\((?:Author|Illustrator|Contributor|Editor|Writer)\)"
        match = re.search(strong_pattern, snippet_text) or re.search(strong_pattern, cleaned_title)
        if match:
            author_cand = clean_author_name(match.group(1))
            if is_valid_author_name(author_cand):
                author = author_cand
                confidence = 0.8
            
    # 2. Fall back to standard "by Capitalized Words" pattern, but validate carefully
    if not author:
        fallback_pattern = r"\bby\s+([A-Z][a-zA-Z.'-]{1,30}(?:\s+[A-Z][a-zA-Z.'-]{1,30}){1,3})"
        for text_to_search in [snippet_text, cleaned_title]:
            for match in re.finditer(fallback_pattern, text_to_search):
                author_cand = clean_author_name(match.group(1))
                if is_valid_author_name(author_cand):
                    author = author_cand
                    confidence = 0.6
                    break
            if author:
                break
                
    # 3. Clean title: If the author name was successfully extracted, and it's present at the end of the title, clean it.
    if author:
        escaped_author = re.escape(author)
        title_suffix_pattern = rf"\s+by\s+{escaped_author}(?:\s*(?:\.\.\.|[.:|-]|$))"
        if re.search(title_suffix_pattern, cleaned_title, flags=re.I):
            cleaned_title = re.sub(title_suffix_pattern, "", cleaned_title, flags=re.I).strip(" -:|")
        else:
            title_suffix_generic = r"\s+by\s+([A-Z][a-zA-Z.'-]{1,30}(?:\s+[A-Z][a-zA-Z.'-]{1,30}){1,3})(?:\s*(?:\.\.\.|[.:|-]|$))"
            match_generic = re.search(title_suffix_generic, cleaned_title)
            if match_generic:
                generic_author = match_generic.group(1)
                generic_words = [w.lower() for w in generic_author.split()]
                if not any(w in EXCLUDED_WORDS for w in generic_words):
                    cleaned_title = re.sub(title_suffix_generic, "", cleaned_title).strip(" -:|")
    
    # 4. Clean up any trailing junk/concatenated search results in title
    if "..." in cleaned_title:
        parts = [p.strip() for p in cleaned_title.split("...")]
        if parts and len(parts[0]) > 5:
            cleaned_title = parts[0]
            
    cleaned_title = re.sub(r"\s*Amazon\.com\s*.*$", "", cleaned_title, flags=re.I).strip(" -:|")
    
    return cleaned_title[:500] or title[:500], author[:255], confidence


def _filter_author_only_candidates(run: ResearchRun, candidates: list[dict]) -> list[dict]:
    """Drop publisher/company "authors" before they become Book rows.

    The pipeline only sells to individual authors.  Seeding a corporate record
    would waste every downstream search query, page crawl, and AI token on a
    lead the quality gate rejects anyway — filter at the Scout stage instead.
    """

    kept: list[dict] = []
    dropped = 0
    for candidate in candidates:
        author_name = (candidate.get("author_name") or "").strip()
        if author_name and is_corporate_author_entity(author_name):
            dropped += 1
            continue
        kept.append(candidate)
    if dropped:
        log_agent_thought(
            run,
            "Scout",
            f"Skipped {dropped} publisher/company records at seed time — only individual authors are kept.",
        )
    return kept


def _candidate_batch_for_run(run: ResearchRun, candidates: list[dict]) -> list[dict]:
    candidates = _filter_author_only_candidates(run, dedupe_book_candidates(candidates))
    if not run.settings_json.get("only_new_books"):
        return candidates[: run.max_books]

    # Filter against the database directly instead of loading every existing
    # book key into memory; candidate batches are bounded (<= a few hundred).
    existing_books = Book.objects.exclude(research_run=run)
    candidate_keys = [
        normalized_book_key(
            candidate["title"],
            candidate.get("author_name"),
            str(candidate.get("asin") or "").strip().upper(),
        )
        for candidate in candidates
    ]
    candidate_asins = {
        str(candidate.get("asin") or "").strip().upper()
        for candidate in candidates
        if candidate.get("asin")
    }
    existing_keys = set(
        existing_books.filter(normalized_key__in=candidate_keys).values_list("normalized_key", flat=True)
    )
    existing_asins = {
        value.upper()
        for value in existing_books.filter(asin__in=candidate_asins).values_list("asin", flat=True)
        if value
    }
    new_candidates: list[dict] = []
    skipped = 0
    for candidate, key in zip(candidates, candidate_keys):
        asin = str(candidate.get("asin") or "").strip().upper()
        if key in existing_keys or (asin and asin in existing_asins):
            skipped += 1
            continue
        existing_keys.add(key)
        if asin:
            existing_asins.add(asin)
        new_candidates.append(candidate)
        if len(new_candidates) >= run.max_books:
            break

    settings_json = dict(run.settings_json or {})
    settings_json["scheduled_dedupe_skipped"] = skipped
    run.settings_json = settings_json
    run.save(update_fields=["settings_json", "updated_at"])
    if skipped:
        log_agent_thought(run, "Scout", f"Skipped {skipped} books already discovered in earlier runs.")
    return new_candidates


def _create_google_books_from_candidates(run: ResearchRun, candidates: list[dict]) -> list[Book]:
    books: list[Book] = []
    for candidate in _candidate_batch_for_run(run, candidates):
        book = Book.objects.create(
            research_run=run,
            title=candidate["title"],
            author_name=candidate.get("author_name", ""),
            asin=candidate.get("asin", ""),
            amazon_book_url=candidate.get("amazon_book_url", ""),
            amazon_source_url=candidate.get("amazon_source_url", ""),
            amazon_source_title=candidate.get("amazon_source_title", ""),
            amazon_source_snippet=candidate.get("amazon_source_snippet", ""),
            category=candidate.get("category", ""),
            review_count=candidate.get("review_count"),
            rating=candidate.get("rating"),
            publisher=candidate.get("publisher", ""),
            publication_date=candidate.get("publication_date", ""),
            cover_image_url=candidate.get("cover_image_url", ""),
            normalized_key=normalized_book_key(candidate["title"], candidate.get("author_name"), candidate.get("asin")),
            book_data_confidence=candidate.get("book_data_confidence", 0.8),
            source_provider=candidate.get("source_provider", run.source_provider),
            source_raw_json=candidate.get("source_raw_json", {}),
        )
        Evidence.objects.create(
            book=book,
            evidence_type="web_search_result",
            field_name="google_books_volume",
            field_value=book.amazon_source_url or book.title,
            source_url=book.amazon_source_url or "https://books.google.com/",
            source_title=book.amazon_source_title,
            source_snippet=book.amazon_source_snippet,
            confidence=book.book_data_confidence,
            is_primary=True,
        )
        books.append(book)
    return books


def _create_booklife_books_from_candidates(run: ResearchRun, candidates: list[dict]) -> list[Book]:
    books: list[Book] = []
    for candidate in _filter_author_only_candidates(run, candidates)[: run.max_books]:
        book = Book.objects.create(
            research_run=run,
            title=candidate["title"],
            author_name=candidate.get("author_name", ""),
            amazon_source_url=candidate.get("amazon_source_url", ""),
            amazon_source_title=candidate.get("amazon_source_title", ""),
            amazon_source_snippet=candidate.get("amazon_source_snippet", ""),
            category=candidate.get("category", ""),
            cover_image_url=candidate.get("cover_image_url", ""),
            normalized_key=normalized_book_key(candidate["title"], candidate.get("author_name"), ""),
            book_data_confidence=candidate.get("book_data_confidence", 0.7),
            source_provider=candidate.get("source_provider", run.source_provider),
            source_raw_json=candidate.get("source_raw_json", {}),
        )
        project_url = candidate.get("booklife_project_url") or book.amazon_source_url
        Evidence.objects.create(
            book=book,
            evidence_type="web_search_result",
            field_name="booklife_project_url",
            field_value=project_url,
            source_url=project_url,
            source_title=book.amazon_source_title,
            source_snippet=book.amazon_source_snippet,
            confidence=book.book_data_confidence,
            is_primary=True,
        )
        books.append(book)
    return books


def _discover_booklife_from_search_index(
    run: ResearchRun,
    booklife_provider,
    selected_categories: list[str],
) -> list[dict]:
    search_provider = get_search_provider(run.settings_json.get("enrichment_provider") or "ddgs")
    max_results = min(max(int(getattr(settings, "APP_MAX_SEARCH_RESULTS_PER_QUERY", 5)), 1), 20)
    candidates: list[dict] = []
    seen_keys: set[str] = set()

    for category_slug in selected_categories:
        for query in booklife_provider.search_index_queries(
            category_slugs=[category_slug],
            age_filter=run.settings_json.get("booklife_age_filter", "all"),
        ):
            raise_if_run_canceled(run)
            log = SearchQueryLog.objects.create(
                research_run=run,
                query=f"BookLife search-index fallback: {query}",
                provider=search_provider.provider_name,
            )
            try:
                results = search_provider.search(query, max_results=max_results)
                log.result_count = len(results)
                log.status = "success"
            except Exception as exc:
                results = []
                log.status = "failed"
                log.error_message = str(exc)[:5000]
            log.save()

            for dto in results:
                candidate = booklife_provider.candidate_from_search_result(dto, category_slug)
                result_class = "unclear"
                confidence = 0.2
                if candidate:
                    result_class = "author_site"
                    confidence = candidate.get("book_data_confidence", 0.5)
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
                if not candidate:
                    continue
                key = normalized_book_key(candidate["title"], candidate.get("author_name"), "")
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                candidate["source_raw_json"]["search_query"] = query
                candidates.append(candidate)
                if len(candidates) >= run.max_books:
                    return candidates[: run.max_books]

    return candidates[: run.max_books]


def _fallback_to_google_books(run: ResearchRun, reason: str) -> list[Book]:
    google_books = GoogleBooksProvider()
    if not google_books.is_configured():
        return []
    log = SearchQueryLog.objects.create(
        research_run=run,
        query=f"Google Books fallback for: {run.keyword}",
        provider=google_books.provider_name,
    )
    try:
        candidates = google_books.discover_books(run.keyword, max_books=run.max_books)
        log.result_count = len(candidates)
        if candidates or not google_books.last_errors:
            log.status = "success"
            log.error_message = reason[:5000]
        else:
            log.status = "failed"
            log.error_message = (
                f"Google Books fallback returned no candidates after {reason}. "
                f"Errors: {' | '.join(google_books.last_errors[:3])}"
            )[:5000]
        return _create_google_books_from_candidates(run, candidates)
    except Exception as exc:
        log.status = "failed"
        log.error_message = f"Google Books fallback failed after {reason}: {exc}"[:5000]
        return []
    finally:
        log.save()


def _discover_site_provider_books(run: ResearchRun) -> list[Book]:
    """Discovery via specialized site providers (Kickstarter, Goodreads
    giveaways, SCBWI, Amazon new releases) that search one site's index and
    parse title/author from the results."""

    site_provider = SITE_DISCOVERY_PROVIDERS[run.source_provider]
    search_provider = get_search_provider(run.settings_json.get("enrichment_provider") or "ddgs")
    max_results = min(max(int(getattr(settings, "APP_MAX_SEARCH_RESULTS_PER_QUERY", 5)), 1), 20)
    log_agent_thought(run, "Scout", f"Running {site_provider.provider_name} discovery for '{run.keyword or 'children\'s picture book'}'.")
    log = SearchQueryLog.objects.create(
        research_run=run,
        query=f"{site_provider.provider_name} site discovery: {run.keyword or 'children\'s picture book'}",
        provider=site_provider.provider_name,
    )
    try:
        candidates, errors = site_provider.discover(
            run.keyword,
            max_books=run.max_books,
            search_provider=search_provider,
            max_results=max_results,
        )
        log.result_count = len(candidates)
        log.status = "success"
        if errors and not candidates:
            log.status = "failed"
            log.error_message = " | ".join(errors[:3])[:5000]
    finally:
        log.save()

    books: list[Book] = []
    for candidate in _candidate_batch_for_run(run, dedupe_book_candidates(candidates)):
        book = Book.objects.create(
            research_run=run,
            title=candidate["title"],
            author_name=candidate.get("author_name", ""),
            asin=candidate.get("asin", ""),
            amazon_book_url=candidate.get("amazon_book_url", ""),
            amazon_source_url=candidate.get("amazon_source_url", ""),
            amazon_source_title=candidate.get("amazon_source_title", ""),
            amazon_source_snippet=candidate.get("amazon_source_snippet", ""),
            normalized_key=normalized_book_key(candidate["title"], candidate.get("author_name"), candidate.get("asin")),
            book_data_confidence=candidate.get("book_data_confidence", 0.45),
            source_provider=candidate.get("source_provider", run.source_provider),
            source_raw_json=candidate.get("source_raw_json", {}),
        )
        Evidence.objects.create(
            book=book,
            evidence_type="amazon_search_result" if candidate.get("asin") else "web_search_result",
            field_name="amazon_book_url" if candidate.get("asin") else "discovery_source_url",
            field_value=book.amazon_book_url or book.amazon_source_url,
            source_url=book.amazon_source_url or book.amazon_book_url,
            source_title=book.amazon_source_title,
            source_snippet=book.amazon_source_snippet,
            confidence=book.book_data_confidence,
            is_primary=True,
        )
        books.append(book)
    return books


def discover_books_from_keyword(run: ResearchRun) -> list[Book]:
    provider = get_search_provider(run.source_provider)
    candidates: list[dict] = []
    queries = discovery_queries(run.keyword)
    log_agent_thought(run, "Scout", f"Generated {len(queries)} search query variants for keyword '{run.keyword}'.")
    max_results = min(max(int(getattr(settings, "APP_MAX_SEARCH_RESULTS_PER_QUERY", 5)), 1), 20)
    max_queries = min(max(int(getattr(settings, "APP_MAX_DISCOVERY_QUERIES", 6)), 1), len(queries))
    failures: list[str] = []
    active_queries = queries[:max_queries]

    def _run_query(query):
        """Network-only worker: one discovery search, errors captured as values."""
        try:
            return provider.search(query, max_results=max_results), None
        except Exception as exc:
            return [], exc

    discovery_batch = map_parallel(_run_query, active_queries)
    for query, (results, search_error) in zip(active_queries, discovery_batch):
        raise_if_run_canceled(run)
        log_agent_thought(run, "Scout", f"Executing discovery search: '{query}'")
        log = SearchQueryLog.objects.create(research_run=run, query=query, provider=provider.provider_name)
        if search_error is None:
            log.result_count = len(results)
            log.status = "success"
        else:
            results = []
            log.status = "failed"
            log.error_message = str(search_error)
            failures.append(str(search_error))
        log.save()
        for dto in results:
            confidence = classify_amazon_search_result(dto.title, dto.url, dto.snippet)
            classification = "amazon_book" if confidence >= 0.6 else "unrelated"
            SearchResult.objects.create(
                search_query_log=log,
                title=dto.title[:500],
                url=dto.url,
                snippet=dto.snippet or "",
                rank=dto.rank,
                provider=dto.provider,
                classification=classification,
                classification_confidence=confidence,
            )
            asin = extract_asin(dto.url)
            if not is_amazon_url(dto.url) or not asin:
                continue
            title, author, book_confidence = guess_title_author(dto.title, dto.snippet)
            normalized_url = normalize_amazon_book_url(dto.url, os.getenv("AMAZON_ASSOCIATE_TAG") or None)
            candidates.append(
                {
                    "title": title,
                    "author_name": author,
                    "asin": asin,
                    "amazon_book_url": normalized_url,
                    "amazon_source_url": dto.url,
                    "amazon_source_title": dto.title,
                    "amazon_source_snippet": dto.snippet or "",
                    "book_data_confidence": book_confidence,
                    "source_provider": provider.provider_name,
                    "source_raw_json": {"query": query, "rank": dto.rank},
                }
            )
            log_agent_thought(run, "Scout", f"Discovered book listing candidate: '{title}' by '{author or 'Unknown'}' (ASIN: {asin})")
        if len(dedupe_book_candidates(candidates)) >= run.max_books:
            break

    if not candidates:
        reason = failures[0] if failures else "web search returned no Amazon book candidates"
        fallback_books = _fallback_to_google_books(run, reason)
        if fallback_books:
            return fallback_books

    if not candidates and failures and len(failures) == max_queries:
        raise RuntimeError(f"All discovery searches failed. First error: {failures[0]}")

    books: list[Book] = []
    for candidate in _candidate_batch_for_run(run, candidates):
        book = Book.objects.create(
            research_run=run,
            title=candidate["title"],
            author_name=candidate.get("author_name", ""),
            asin=candidate.get("asin", ""),
            amazon_book_url=candidate.get("amazon_book_url", ""),
            amazon_source_url=candidate.get("amazon_source_url", ""),
            amazon_source_title=candidate.get("amazon_source_title", ""),
            amazon_source_snippet=candidate.get("amazon_source_snippet", ""),
            normalized_key=normalized_book_key(candidate["title"], candidate.get("author_name"), candidate.get("asin")),
            book_data_confidence=candidate.get("book_data_confidence", 0.35),
            source_provider=candidate.get("source_provider", run.source_provider),
            source_raw_json=candidate.get("source_raw_json", {}),
        )
        Evidence.objects.create(
            book=book,
            evidence_type="amazon_search_result",
            field_name="amazon_book_url",
            field_value=book.amazon_book_url,
            source_url=book.amazon_source_url or book.amazon_book_url,
            source_title=book.amazon_source_title,
            source_snippet=book.amazon_source_snippet,
            confidence=book.book_data_confidence,
            is_primary=True,
        )
        books.append(book)
    return books


def run_research_pipeline(research_run_id) -> None:
    run = ResearchRun.objects.get(id=research_run_id)
    raise_if_run_canceled(run)
    run.mark_running()
    try:
        if run.source_provider in {"csv", "manual"}:
            books = list(run.books.all()[: run.max_books])
        elif run.source_provider == "amazon_creators":
            from leadfinder.services.amazon.amazon_creators_provider import AmazonCreatorsProvider
            candidates = AmazonCreatorsProvider().discover_books(run.keyword, max_books=run.max_books)
            books = []
            for candidate in _filter_author_only_candidates(run, candidates):
                book = Book.objects.create(
                    research_run=run,
                    title=candidate["title"],
                    author_name=candidate.get("author_name", ""),
                    asin=candidate.get("asin", ""),
                    amazon_book_url=candidate.get("amazon_book_url", ""),
                    amazon_source_url=candidate.get("amazon_source_url", ""),
                    amazon_source_title=candidate.get("amazon_source_title", ""),
                    amazon_source_snippet=candidate.get("amazon_source_snippet", ""),
                    normalized_key=normalized_book_key(candidate["title"], candidate.get("author_name"), candidate.get("asin")),
                    book_data_confidence=candidate.get("book_data_confidence", 0.9),
                    source_provider=candidate.get("source_provider", run.source_provider),
                    source_raw_json=candidate.get("source_raw_json", {}),
                )
                Evidence.objects.create(
                    book=book,
                    evidence_type="amazon_search_result",
                    field_name="amazon_book_url",
                    field_value=book.amazon_book_url,
                    source_url=book.amazon_source_url or book.amazon_book_url,
                    source_title=book.amazon_source_title,
                    source_snippet=book.amazon_source_snippet,
                    confidence=book.book_data_confidence,
                    is_primary=True,
                )
                books.append(book)
        elif run.source_provider == "google_books":
            candidates = GoogleBooksProvider().discover_books(run.keyword, max_books=run.max_books)
            books = _create_google_books_from_candidates(run, candidates)
        elif run.source_provider in SITE_DISCOVERY_PROVIDERS:
            books = _discover_site_provider_books(run)
        elif run.source_provider == "booklife":
            from leadfinder.services.booklife import BookLifeProjectProvider, BookLifeRobotsBlocked

            provider = BookLifeProjectProvider(
                fetch_project_details=os.getenv("BOOKLIFE_FETCH_PROJECT_DETAILS", "").lower() in {"1", "true", "yes", "on"}
            )
            selected_categories = list(run.settings_json.get("booklife_categories") or ["all"])
            labels = run.settings_json.get("booklife_category_labels") or selected_categories
            log = SearchQueryLog.objects.create(
                research_run=run,
                query=f"BookLife categories: {', '.join(labels)}",
                provider=provider.provider_name,
            )
            try:
                candidates = provider.discover_books(
                    category_slugs=selected_categories,
                    age_filter=run.settings_json.get("booklife_age_filter", "all"),
                    max_books=run.max_books,
                )
                log.result_count = len(candidates)
                log.status = "success"
            except BookLifeRobotsBlocked as exc:
                log.status = "success"
                log.error_message = f"Direct BookLife fetch skipped: {exc} Falling back to search-index snippets."[:5000]
                candidates = _discover_booklife_from_search_index(run, provider, selected_categories)
                log.result_count = len(candidates)
            except Exception as exc:
                log.status = "failed"
                log.error_message = str(exc)[:5000]
                raise
            finally:
                log.save()
            books = _create_booklife_books_from_candidates(run, candidates)
        else:
            books = discover_books_from_keyword(run)

        log_agent_thought(run, "Scout", f"Discovery phase complete. Found {len(books)} candidate books to process.")
        log_agent_thought(run, "Harvester", f"Harvester initialized. Beginning detail collection, creator crawling, and video search for {len(books)} books.")

        scheduled_target = int(run.settings_json.get("target_verified_leads") or 0)
        scheduled_requirement = run.settings_json.get("require_contact", "email_or_phone")
        scheduled_verified_count = 0
        processed_books_count = 0
        verify_mx = bool(run.settings_json.get("verify_email_mx", True))
        progress_lock = threading.Lock()
        stop_event = threading.Event()

        def _book_has_verified_contact(lead) -> bool:
            qualification = Q(verification_status="verified")
            if not verify_mx:
                qualification |= Q(
                    channel="email",
                    verification_status="other",
                    verification_score__gte=75,
                    deliverability_status="unknown",
                )
            verified_candidates = lead.contact_candidates.filter(qualification)
            if scheduled_requirement == "email_only":
                verified_candidates = verified_candidates.filter(channel="email")
            else:
                verified_candidates = verified_candidates.filter(channel__in=["email", "phone"])
            return verified_candidates.exists()

        def _process_one_book(book) -> bool:
            """Process one book; return True when it yielded a verified contactable lead."""
            if stop_event.is_set():
                return False
            close_old_connections()
            try:
                raise_if_run_canceled(run)
                if not isinstance(book.source_raw_json, dict):
                    book.source_raw_json = {}
                book.source_raw_json["processing_status"] = "processing"
                book.save(update_fields=["source_raw_json", "updated_at"])

                try:
                    lead = process_book(
                        book,
                        run_video_search=bool(run.settings_json.get("run_video_search", True)),
                        run_ai_extraction=bool(run.settings_json.get("run_groq_ai_extraction", True)),
                        verify_email_mx=verify_mx,
                    )
                    hit = _book_has_verified_contact(lead)
                    book.refresh_from_db()
                    if not isinstance(book.source_raw_json, dict):
                        book.source_raw_json = {}
                    book.source_raw_json["processing_status"] = "completed"
                    book.source_raw_json["processing_stage"] = "Complete"
                    book.source_raw_json["processing_detail"] = "Evidence and review data are ready."
                    book.save(update_fields=["source_raw_json", "updated_at"])
                    return hit
                except RunCanceled:
                    try:
                        book.refresh_from_db()
                        if not isinstance(book.source_raw_json, dict):
                            book.source_raw_json = {}
                        book.source_raw_json["processing_status"] = "failed"
                        book.source_raw_json["processing_stage"] = "Canceled"
                        book.source_raw_json["processing_detail"] = "The runner was stopped before this item completed."
                        book.save(update_fields=["source_raw_json", "updated_at"])
                    except Exception:
                        pass
                    raise
                except Exception as exc:
                    try:
                        book.refresh_from_db()
                    except Exception:
                        pass
                    if not isinstance(book.source_raw_json, dict):
                        book.source_raw_json = {}
                    book.source_raw_json["processing_status"] = "failed"
                    book.source_raw_json["processing_stage"] = "Needs a valid evidence match"
                    book.source_raw_json["processing_detail"] = str(exc)[:5000]
                    warnings = book.source_raw_json
                    warnings.setdefault("book_processing_errors", []).append(str(exc))
                    book.source_raw_json = warnings
                    book.save(update_fields=["source_raw_json", "updated_at"])
                    return False
            finally:
                close_old_connections()

        def _record_result(hit: bool) -> None:
            nonlocal processed_books_count, scheduled_verified_count
            with progress_lock:
                processed_books_count += 1
                if hit:
                    scheduled_verified_count += 1
                if scheduled_target:
                    progress = dict(run.settings_json or {})
                    progress["scheduled_verified_count"] = scheduled_verified_count
                    progress["scheduled_processed_books"] = processed_books_count
                    progress["scheduled_target_reached"] = scheduled_verified_count >= scheduled_target
                    run.settings_json = progress
                    run.save(update_fields=["settings_json", "updated_at"])
                if scheduled_target and scheduled_verified_count >= scheduled_target:
                    stop_event.set()

        workers = max(1, min(int(getattr(settings, "APP_PIPELINE_WORKERS", 1) or 1), 8, max(1, len(books))))
        # In-memory SQLite (test runs) serializes writers with table locks that
        # busy-timeout cannot wait out; keep those runs strictly sequential.
        db_name = str(connection.settings_dict.get("NAME") or "")
        if ":memory:" in db_name or "mode=memory" in db_name:
            workers = 1
        if workers > 1:
            log_agent_thought(run, "Harvester", f"Processing books with {workers} parallel workers.")
        canceled = None
        try:
            if workers == 1:
                # Sequential path: same thread/connection — required for tests
                # and in-memory SQLite, which lock out secondary connections.
                for book in books:
                    hit = _process_one_book(book)
                    _record_result(hit)
                    raise_if_run_canceled(run)
                    if stop_event.is_set():
                        log_agent_thought(
                            run,
                            "Coordinator",
                            f"Scheduled target reached: {scheduled_verified_count} verified contactable leads.",
                        )
                        break
            else:
                with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"pipeline-run-{run.id}") as pool:
                    futures = {pool.submit(_process_one_book, book): book for book in books}
                    for future in as_completed(futures):
                        try:
                            hit = future.result()
                        except RunCanceled as exc:
                            canceled = exc
                            stop_event.set()
                            for pending in futures:
                                pending.cancel()
                            break
                        _record_result(hit)
                        raise_if_run_canceled(run)
                        if stop_event.is_set():
                            log_agent_thought(
                                run,
                                "Coordinator",
                                f"Scheduled target reached: {scheduled_verified_count} verified contactable leads.",
                            )
                            for pending in futures:
                                pending.cancel()
                            break
        finally:
            if canceled is not None:
                raise canceled
        log_agent_thought(run, "Coordinator", f"Pipeline run completed successfully. Finalized and compiled leads database.")
        run.mark_completed()
        from leadfinder.services.notify import notify_run_completed

        notify_run_completed(run)
    except RunCanceled:
        run.mark_canceled()
    except Exception as exc:
        run.mark_failed(str(exc))
        raise
