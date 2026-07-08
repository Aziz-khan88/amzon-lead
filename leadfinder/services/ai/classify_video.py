from __future__ import annotations

from .groq_client import GroqJSONClient
from .schemas import VideoClassification
from leadfinder.utils.source_confidence import clamp_confidence


def classify_video(video_data: dict, use_ai: bool = True) -> VideoClassification:
    prompt = (
        "Classify book trailer or animated promo video evidence.\n"
        "Your JSON output MUST contain exactly the following keys with these types:\n"
        "- matches_book: boolean or null\n"
        "- matches_author: boolean or null\n"
        "- is_book_trailer: boolean\n"
        "- is_animated_video: boolean. Set to true ONLY if the title or text explicitly indicates it is animated (e.g., contains 'animated', 'animation', 'motion graphics', etc.). Do not assume a trailer is animated unless explicitly stated.\n"
        "- is_read_aloud: boolean\n"
        "- is_author_interview: boolean\n"
        "- confidence: float between 0 and 1\n"
        "- reason: string"
    )
    ai = GroqJSONClient().complete_json(prompt, video_data) if use_ai else None
    if ai:
        return VideoClassification(
            matches_book=ai.get("matches_book"),
            matches_author=ai.get("matches_author"),
            is_book_trailer=bool(ai.get("is_book_trailer")),
            is_animated_video=bool(ai.get("is_animated_video")),
            is_read_aloud=bool(ai.get("is_read_aloud")),
            is_author_interview=bool(ai.get("is_author_interview")),
            confidence=clamp_confidence(ai.get("confidence")),
            reason=ai.get("reason") or "",
        )
    text = " ".join(str(video_data.get(key) or "") for key in ["title", "description", "snippet"]).lower()
    is_trailer = "trailer" in text
    is_animated = any(term in text for term in ["animated", "animation", "motion graphics"])
    is_read_aloud = any(term in text for term in ["read aloud", "read-aloud", "storytime"])
    confidence = 0.8 if is_animated or is_trailer or is_read_aloud else 0.2
    return VideoClassification(
        matches_book=True if video_data.get("book_title", "").lower() in text else None,
        matches_author=True if video_data.get("author_name", "").lower() in text else None,
        is_book_trailer=is_trailer,
        is_animated_video=is_animated,
        is_read_aloud=is_read_aloud,
        is_author_interview="interview" in text,
        confidence=confidence,
        reason="Deterministic keyword fallback; Groq key unavailable or request failed.",
    )


def choose_video_status(classifications: list[VideoClassification], search_completed: bool = True) -> tuple[str, float, str]:
    if not search_completed:
        return "not_checked", 0, "Video search was not completed."
    meaningful = [item for item in classifications if item.confidence >= 0.4]
    if any(item.is_animated_video and item.confidence >= 0.75 for item in meaningful):
        best = max((item for item in meaningful if item.is_animated_video), key=lambda item: item.confidence)
        return "found_animated_video", best.confidence, best.reason
    if any(item.is_book_trailer and item.confidence >= 0.75 for item in meaningful):
        best = max((item for item in meaningful if item.is_book_trailer), key=lambda item: item.confidence)
        return "found_trailer", best.confidence, best.reason
    if meaningful and all(item.is_read_aloud for item in meaningful):
        best = max(meaningful, key=lambda item: item.confidence)
        return "found_read_aloud_only", best.confidence, best.reason
    if meaningful:
        best = max(meaningful, key=lambda item: item.confidence)
        return "unclear", best.confidence, best.reason
    return "no_public_video_found", 0.7, "No public video found in searched sources."
