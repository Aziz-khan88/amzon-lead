from __future__ import annotations

from .groq_client import GroqJSONClient
from .schemas import BookClassification
from leadfinder.utils.source_confidence import clamp_confidence


CHILD_TERMS = {"children", "kids", "picture book", "bedtime", "storybook", "juvenile", "early reader"}
PICTURE_TERMS = {"picture book", "illustrated", "illustrator", "coloring", "storybook"}


def classify_book(book_data: dict, snippets: list[str] | None = None, use_ai: bool = True) -> BookClassification:
    text = " ".join(
        [
            str(book_data.get("title") or ""),
            str(book_data.get("category") or ""),
            str(book_data.get("publisher") or ""),
            " ".join(snippets or []),
        ]
    ).lower()
    prompt = (
        "Classify whether this book is a children's book and/or a picture/illustrated book.\n"
        "Your JSON output MUST contain exactly the following keys with these types:\n"
        "- is_childrens_book: boolean or null\n"
        "- is_picture_or_illustrated_book: boolean or null\n"
        "- confidence: float between 0 and 1\n"
        "- age_range_guess: string or null\n"
        "- reason: string\n"
        "- reject_reason: string or null"
    )
    ai = GroqJSONClient().complete_json(prompt, book_data) if use_ai else None
    if ai:
        return BookClassification(
            is_childrens_book=ai.get("is_childrens_book"),
            is_picture_or_illustrated_book=ai.get("is_picture_or_illustrated_book"),
            confidence=clamp_confidence(ai.get("confidence")),
            age_range_guess=ai.get("age_range_guess"),
            reason=ai.get("reason") or "",
            reject_reason=ai.get("reject_reason"),
        )
    is_child = any(term in text for term in CHILD_TERMS)
    is_picture = any(term in text for term in PICTURE_TERMS)
    confidence = 0.75 if is_child else 0.25
    if is_picture:
        confidence = max(confidence, 0.8)
    return BookClassification(
        is_childrens_book=is_child if text else None,
        is_picture_or_illustrated_book=is_picture if text else None,
        confidence=confidence,
        reason="Deterministic keyword fallback; Groq key unavailable or request failed.",
        reject_reason=None if is_child else "No explicit children's-book signal found.",
    )
