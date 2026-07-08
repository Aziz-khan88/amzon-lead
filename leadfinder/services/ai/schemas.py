from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class BookClassification:
    is_childrens_book: bool | None
    is_picture_or_illustrated_book: bool | None
    confidence: float
    age_range_guess: str | None = None
    reason: str = ""
    reject_reason: str | None = None


@dataclass(slots=True)
class SearchClassification:
    classification: str
    confidence: float
    reason: str = ""


@dataclass(slots=True)
class ContactExtraction:
    canonical_website: str | None = None
    contact_page_url: str | None = None
    public_email: str | None = None
    public_phone: str | None = None
    location: str | None = None
    instagram_url: str | None = None
    facebook_url: str | None = None
    tiktok_url: str | None = None
    youtube_url: str | None = None
    linkedin_url: str | None = None
    goodreads_url: str | None = None
    publisher_url: str | None = None
    agent_name: str | None = None
    representation_email: str | None = None
    publicist_email: str | None = None
    confidence: float = 0
    warnings: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class VideoClassification:
    matches_book: bool | None
    matches_author: bool | None
    is_book_trailer: bool
    is_animated_video: bool
    is_read_aloud: bool
    is_author_interview: bool
    confidence: float
    reason: str = ""


@dataclass(slots=True)
class ParsedBlogReview:
    book_title: str | None
    author_name: str | None
    confidence: float
    reason: str = ""

