from __future__ import annotations

import hashlib
import os
import re
from urllib.parse import urlparse

from django.utils import timezone

from leadfinder.models import Evidence, SocialProfileAudit
from leadfinder.services.crawl.contact_regex import extract_emails, extract_phones
from leadfinder.services.crawl.social_contact_crawler import (
    crawl_social_contact_pages,
    fetch_public_html,
)
from leadfinder.services.pipeline.lead_validator import validate_phone_number
from leadfinder.services.pipeline.source_audit import is_catalog_or_platform_source
from leadfinder.utils.url_safety import is_safe_public_url


PLATFORM_FIELDS = {
    "instagram": "instagram_url",
    "facebook": "facebook_url",
    "tiktok": "tiktok_url",
    "youtube": "youtube_url",
    "linkedin": "linkedin_url",
}
BIO_LINK_HOSTS = {
    "beacons.ai",
    "bio.site",
    "carrd.co",
    "linktr.ee",
    "linktree.com",
    "solo.to",
    "substack.com",
}


def _normalized_handle(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if not parts:
        return ""
    return parts[-1].lstrip("@").lower()[:255]


def _youtube_profile(url: str) -> tuple[str, str, str] | None:
    api_key = os.getenv("YOUTUBE_API_KEY", "")
    handle = _normalized_handle(url)
    if not api_key or not handle:
        return None
    try:
        from googleapiclient.discovery import build

        service = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
        request = service.channels().list(part="snippet", forHandle=handle)
        response = request.execute()
        item = (response.get("items") or [None])[0]
        if not item:
            return None
        snippet = item.get("snippet") or {}
        return snippet.get("title") or "", snippet.get("description") or "", "youtube_api"
    except Exception:
        return None


def _public_profile_html(url: str) -> tuple[str, str, list[str], str, str] | None:
    page = fetch_public_html(url)
    if page is None:
        return None
    return page.title, page.text, page.links, page.url, page.html


def _social_identity_matches(author_name: str, book_title: str, *values: str) -> bool:
    """Require a full-name match, or surname plus strong book-title support."""
    text = re.sub(r"[^a-z0-9]+", " ", " ".join(values).lower()).strip()
    compact_text = text.replace(" ", "")
    author_tokens = re.findall(r"[a-z0-9]+", (author_name or "").lower())
    if not author_tokens:
        return False
    if " ".join(author_tokens) in text or "".join(author_tokens) in compact_text:
        return True
    title_tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", (book_title or "").lower())
        if len(token) >= 4
    ]
    surname_present = len(author_tokens[-1]) >= 4 and author_tokens[-1] in text
    required_title_matches = min(2, len(title_tokens))
    return bool(
        surname_present
        and required_title_matches
        and sum(token in text for token in title_tokens) >= required_title_matches
    )


def _external_links(links: list[str]) -> list[str]:
    result = []
    for link in links:
        if not is_safe_public_url(link) or is_catalog_or_platform_source(link):
            continue
        if link not in result:
            result.append(link)
    return result[:10]


def _is_supported_bio_link(url: str, author) -> bool:
    """Limit second-hop requests to bio-link services and known author domains."""

    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if any(host == bio_host or host.endswith(f".{bio_host}") for bio_host in BIO_LINK_HOSTS):
        return True
    author_hosts = {
        (urlparse(getattr(author, field, "") or "").hostname or "").lower()
        for field in ("canonical_website", "contact_page_url")
    }
    author_hosts.discard("")
    return any(host == author_host or host.endswith(f".{author_host}") for author_host in author_hosts)


def _append_contact(
    contacts: list[dict[str, str]],
    *,
    field: str,
    value: str,
    source_url: str,
    source_title: str,
    source_snippet: str,
    confidence: float,
) -> None:
    if not any(item["field"] == field and item["value"] == value for item in contacts):
        contacts.append(
            {
                "field": field,
                "value": value,
                "source_url": source_url,
                "source_title": source_title[:500],
                "source_snippet": source_snippet[:500],
                "confidence": confidence,
            }
        )


def harvest_social_profiles(lead) -> list[SocialProfileAudit]:
    """Inspect publicly accessible social profiles without bypassing access controls."""
    author = lead.author_profile
    if not author:
        return []
    audits: list[SocialProfileAudit] = []
    for platform, field_name in PLATFORM_FIELDS.items():
        profile_url = getattr(author, field_name, "") or ""
        if not profile_url:
            continue
        defaults = {
            "normalized_handle": _normalized_handle(profile_url),
            "fetch_status": "pending",
            "failure_reason": "",
        }
        audit, _ = SocialProfileAudit.objects.update_or_create(
            lead=lead,
            author_profile=author,
            platform=platform,
            profile_url=profile_url,
            defaults=defaults,
        )
        profile_name = ""
        profile_text = ""
        links: list[str] = []
        content_hash = ""
        fetch_method = ""
        final_url = profile_url

        youtube = _youtube_profile(profile_url) if platform == "youtube" else None
        if youtube:
            profile_name, profile_text, fetch_method = youtube
            content_hash = hashlib.sha256(profile_text.encode("utf-8", errors="ignore")).hexdigest()
        else:
            page = _public_profile_html(profile_url)
            if not page:
                audit.fetch_status = "blocked"
                audit.failure_reason = "The public profile was unavailable or disallowed by robots/access controls."
                audit.fetch_method = "public_html"
                audit.fetched_at = timezone.now()
                audit.save(update_fields=["fetch_status", "failure_reason", "fetch_method", "fetched_at", "updated_at"])
                audits.append(audit)
                continue
            profile_name, profile_text, links, final_url, html = page
            fetch_method = "public_html"
            content_hash = hashlib.sha256(html.encode("utf-8", errors="ignore")).hexdigest()

        identity_match = _social_identity_matches(
            lead.book.author_name,
            lead.book.title,
            profile_name,
            profile_text,
            final_url,
        )
        identity_score = 90 if identity_match else 30
        contacts = []
        if identity_match:
            for email in extract_emails(profile_text):
                _append_contact(
                    contacts,
                    field="public_email",
                    value=email,
                    source_url=final_url,
                    source_title=profile_name,
                    source_snippet=profile_text,
                    confidence=0.85,
                )
            for phone in extract_phones(profile_text):
                normalized_phone = validate_phone_number(phone)
                if normalized_phone:
                    _append_contact(
                        contacts,
                        field="public_phone",
                        value=normalized_phone,
                        source_url=final_url,
                        source_title=profile_name,
                        source_snippet=profile_text,
                        confidence=0.85,
                    )

        external_urls = _external_links(links)
        bio_link_urls = [url for url in external_urls if _is_supported_bio_link(url, author)]
        if identity_match and bio_link_urls:
            for bio_page in crawl_social_contact_pages(bio_link_urls):
                provenance = (
                    f"Linked from the identity-matched {platform} profile "
                    f"{profile_name or profile_url}. {bio_page.text}"
                )
                for email in bio_page.emails:
                    _append_contact(
                        contacts,
                        field="public_email",
                        value=email,
                        source_url=bio_page.url,
                        source_title=bio_page.title or profile_name,
                        source_snippet=provenance,
                        confidence=0.82,
                    )
                for phone in bio_page.phones:
                    _append_contact(
                        contacts,
                        field="public_phone",
                        value=phone,
                        source_url=bio_page.url,
                        source_title=bio_page.title or profile_name,
                        source_snippet=provenance,
                        confidence=0.82,
                    )
        audit.fetch_method = fetch_method
        audit.fetch_status = "fetched"
        audit.profile_name = profile_name[:500]
        audit.biography = profile_text[:5000]
        audit.external_urls_json = external_urls
        audit.extracted_contacts_json = contacts
        audit.identity_score = identity_score
        audit.content_hash = content_hash
        audit.fetched_at = timezone.now()
        audit.failure_reason = "" if identity_match else "Profile content did not sufficiently match the target author and book."
        audit.save()

        Evidence.objects.update_or_create(
            lead=lead,
            author_profile=author,
            evidence_type="social_profile",
            field_name=f"{platform}_profile_audit",
            field_value=profile_url,
            source_url=final_url,
            defaults={
                "source_title": profile_name[:500],
                "source_snippet": profile_text[:500],
                "confidence": identity_score / 100,
                "is_primary": False,
            },
        )
        for item in contacts:
            Evidence.objects.update_or_create(
                lead=lead,
                author_profile=author,
                evidence_type="social_profile",
                field_name=item["field"],
                field_value=item["value"],
                source_url=item["source_url"],
                defaults={
                    "source_title": item["source_title"],
                    "source_snippet": item["source_snippet"],
                    "confidence": item["confidence"],
                    "is_primary": True,
                },
            )
        for external_url in external_urls:
            Evidence.objects.update_or_create(
                lead=lead,
                author_profile=author,
                evidence_type="social_profile",
                field_name="social_external_url",
                field_value=external_url,
                source_url=final_url,
                defaults={"source_title": profile_name[:500], "confidence": 0.75},
            )
        audits.append(audit)
    return audits
