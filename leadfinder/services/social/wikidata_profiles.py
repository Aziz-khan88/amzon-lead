"""Free, no-API-key author profile discovery via Wikidata + Wikipedia.

Wikidata author entities carry structured, community-maintained identifiers:
official website (P856), X/Twitter (P2002), Instagram (P2003), Facebook
(P2013), YouTube channel (P2397), LinkedIn (P6634), and Goodreads author ID
(P2963).  One ``wbsearchentities`` + one ``wbgetentities`` call turns an
author name into a set of verified profile URLs — completely free, no key,
no scraping.  Results are cached for 24 hours and require a name-token match
so a same-named stranger never becomes lead evidence.
"""

from __future__ import annotations

import logging
import re
from hashlib import sha256
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache

from leadfinder.utils.normalize import normalize_text

logger = logging.getLogger(__name__)

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "BookTrailerLeadFinder/1.0 (public author profile reconciliation)"

_AUTHOR_DESCRIPTION_HINTS = (
    "author",
    "writer",
    "illustrator",
    "novelist",
    "poet",
    "children",
    "cartoonist",
)

_SOCIAL_CLAIMS = {
    "P2003": ("instagram_url", "https://www.instagram.com/{value}"),
    "P2013": ("facebook_url", "https://www.facebook.com/{value}"),
    "P2397": ("youtube_url", "https://www.youtube.com/channel/{value}"),
    "P6634": ("linkedin_url", "https://www.linkedin.com/in/{value}"),
    "P2963": ("goodreads_url", "https://www.goodreads.com/author/show/{value}"),
}


def _timeout() -> int:
    return int(getattr(settings, "APP_REQUEST_TIMEOUT_SECONDS", 15))


def _get_json(session: requests.Session, params: dict[str, Any]) -> dict[str, Any]:
    response = session.get(
        WIKIDATA_API,
        params=params,
        timeout=_timeout(),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _name_tokens(name: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", normalize_text(name).lower())
        if len(token) >= 2
    }


def _label_matches(author_name: str, label: str) -> bool:
    """Every meaningful token of the query must appear in the entity label."""
    wanted = _name_tokens(author_name)
    found = _name_tokens(label)
    return bool(wanted) and wanted.issubset(found)


def _claim_values(entity: dict[str, Any], prop: str) -> list[str]:
    values: list[str] = []
    for claim in entity.get("claims", {}).get(prop, []) or []:
        datavalue = (claim.get("mainsnak") or {}).get("datavalue") or {}
        value = datavalue.get("value")
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    return values


def find_author_profiles(
    author_name: str, *, session: requests.Session | None = None
) -> dict[str, Any] | None:
    """Return verified public profile URLs for an author, or None.

    Free Wikidata API, no key.  Cached 24h per normalized author name.
    """
    cleaned = " ".join((author_name or "").split())
    if len(cleaned) < 3:
        return None

    digest = sha256(normalize_text(cleaned).lower().encode("utf-8")).hexdigest()[:24]
    cache_key = f"wikidata-author:v1:{digest}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return dict(cached)
    if cache.get(cache_key + ":miss"):
        return None

    http = session or requests.Session()
    try:
        search = _get_json(
            http,
            {
                "action": "wbsearchentities",
                "search": cleaned,
                "language": "en",
                "type": "item",
                "limit": 5,
                "format": "json",
            },
        )
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Wikidata author search failed for %r: %s", cleaned, exc)
        return None

    candidates = [item for item in search.get("search", []) or [] if isinstance(item, dict)]
    entity_id = ""
    entity_label = ""
    entity_description = ""
    for item in candidates:
        label = str(item.get("label") or "")
        if not _label_matches(cleaned, label):
            continue
        description = str(item.get("description") or "").lower()
        entity_id = str(item.get("id") or "")
        entity_label = label
        entity_description = description
        if any(hint in description for hint in _AUTHOR_DESCRIPTION_HINTS):
            break  # best possible match; stop scanning
    if not entity_id:
        cache.set(cache_key + ":miss", 1, timeout=60 * 60 * 24)
        return None

    try:
        entities = _get_json(
            http,
            {
                "action": "wbgetentities",
                "ids": entity_id,
                "props": "claims|sitelinks",
                "sitefilter": "enwiki",
                "format": "json",
            },
        )
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Wikidata entity fetch failed for %s: %s", entity_id, exc)
        return None

    entity = (entities.get("entities") or {}).get(entity_id) or {}
    profiles: dict[str, Any] = {
        "entity_id": entity_id,
        "entity_url": f"https://www.wikidata.org/wiki/{entity_id}",
        "entity_label": entity_label,
        "entity_description": entity_description,
        "canonical_website": "",
        "wikipedia_url": "",
        "instagram_url": "",
        "facebook_url": "",
        "tiktok_url": "",
        "youtube_url": "",
        "linkedin_url": "",
        "goodreads_url": "",
    }
    websites = _claim_values(entity, "P856")
    if websites:
        profiles["canonical_website"] = websites[0]
    for prop, (field, template) in _SOCIAL_CLAIMS.items():
        values = _claim_values(entity, prop)
        if values:
            profiles[field] = template.format(value=values[0])
    sitelinks = entity.get("sitelinks") or {}
    enwiki = (sitelinks.get("enwiki") or {}).get("title") or ""
    if enwiki:
        profiles["wikipedia_url"] = f"https://en.wikipedia.org/wiki/{enwiki.replace(' ', '_')}"

    has_any_profile = any(
        profiles[field]
        for field in (
            "canonical_website",
            "wikipedia_url",
            "instagram_url",
            "facebook_url",
            "youtube_url",
            "linkedin_url",
            "goodreads_url",
        )
    )
    if not has_any_profile:
        cache.set(cache_key + ":miss", 1, timeout=60 * 60 * 24)
        return None

    description_boost = any(hint in entity_description for hint in _AUTHOR_DESCRIPTION_HINTS)
    profiles["confidence"] = 0.8 if description_boost else 0.65
    cache.set(cache_key, profiles, timeout=60 * 60 * 24)
    return profiles
