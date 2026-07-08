from __future__ import annotations

import re
from .groq_client import GroqJSONClient
from .schemas import ParsedBlogReview
from leadfinder.utils.source_confidence import clamp_confidence


def clean_parsed_field(val: str | None) -> str | None:
    if not val:
        return None
    val = val.strip(" \"'“”.:,-—–|•*")
    val = re.sub(r"\s+", " ", val)
    return val if len(val) >= 2 else None


def parse_blog_review_fallback(title: str, snippet: str) -> ParsedBlogReview:
    """
    Robust regex and heuristic fallback for parsing book title and author name from blog review text.
    """
    text = f"{title} {snippet}"
    
    # Try looking for common review formats in the title
    # Format: "Review: Book Title by Author Name"
    # Format: "Book Title by Author Name | The Children's Book Review"
    cleaned_title = re.sub(
        r"\b(Book Review|Review of|Review|Author Interview|Interview|Feature|Spotlight|Blog Tour|New Book|Review & Giveaway)\b[:\-—–|•]*", 
        "", 
        title, 
        flags=re.I
    ).strip()
    
    # Remove common site signatures
    cleaned_title = re.sub(
        r"\|?\s*(The Children's Book Review|From the Mixed-Up Files|A Fuse 8 Production|Seven Impossible Things|KidLit411|Book Craic|Read It Daddy|LitPick|What Do We Do All Day)$", 
        "", 
        cleaned_title, 
        flags=re.I
    ).strip(" -:|")
    
    # Look for "by [Author]" in the cleaned title
    by_match = re.search(r"\bby\s+([A-Z][A-Za-z0-9 .,'&-]{2,90}?)(?:\s+\(|[.;|#\n\r]|$)", cleaned_title)
    if by_match:
        author = by_match.group(1).strip()
        book_title = re.split(r"\s+by\s+", cleaned_title, maxsplit=1, flags=re.I)[0].strip()
        
        parsed_book = clean_parsed_field(book_title)
        parsed_author = clean_parsed_field(author)
        if parsed_book and parsed_author:
            return ParsedBlogReview(
                book_title=parsed_book,
                author_name=parsed_author,
                confidence=0.7,
                reason="Fallback Regex: successfully matched title/author from title text."
            )
            
    # Try parsing from title or snippet generally using "by" separator
    combined = f"{cleaned_title} {snippet}"
    by_matches = list(re.finditer(r"\b([A-Za-z0-9 .,'“”-]{5,100}?)\s+by\s+([A-Z][A-Za-z0-9 .,'&-]{2,50})\b", combined))
    if by_matches:
        # Take the first match
        match = by_matches[0]
        parsed_book = clean_parsed_field(match.group(1))
        parsed_author = clean_parsed_field(match.group(2))
        
        # Make sure book title doesn't contain bad words or look too generic
        if parsed_book and parsed_author and "review" not in parsed_book.lower() and "interview" not in parsed_book.lower():
            return ParsedBlogReview(
                book_title=parsed_book,
                author_name=parsed_author,
                confidence=0.6,
                reason="Fallback Regex: successfully matched title/author from combined text."
            )
            
    return ParsedBlogReview(
        book_title=None,
        author_name=None,
        confidence=0.0,
        reason="Fallback Regex: could not determine title/author with confidence."
    )


def parse_blog_review(title: str, snippet: str, use_ai: bool = True) -> ParsedBlogReview:
    """
    Parses a blog review search result to extract the featured book title and author name.
    Utilizes Groq AI JSON extraction with a solid deterministic regex fallback.
    """
    title_clean = (title or "").strip()
    snippet_clean = (snippet or "").strip()
    
    if not title_clean:
        return ParsedBlogReview(book_title=None, author_name=None, confidence=0.0, reason="Empty input title.")

    if not use_ai:
        return parse_blog_review_fallback(title_clean, snippet_clean)

    prompt = (
        "Extract the primary children's or illustrated book title and its author's name from this blog review/feature search result.\n"
        "Your JSON output MUST contain exactly the following keys with these types:\n"
        "- book_title: string or null\n"
        "- author_name: string or null\n"
        "- confidence: float between 0 and 1\n"
        "- reason: string\n"
        "\n"
        "Ensure you ignore common words like 'Review', 'Interview', 'Features', 'Blog Tour', etc.\n"
        "Only extract the primary book and its author discussed in the title and snippet."
    )
    
    payload = {
        "search_result_title": title_clean,
        "search_result_snippet": snippet_clean
    }
    
    try:
        ai = GroqJSONClient().complete_json(prompt, payload)
    except Exception:
        ai = None
        
    if ai:
        book_title = clean_parsed_field(ai.get("book_title"))
        author_name = clean_parsed_field(ai.get("author_name"))
        confidence = clamp_confidence(ai.get("confidence") or 0.8)
        reason = ai.get("reason") or "Successfully parsed using Groq JSON extraction."
        
        if book_title and author_name:
            return ParsedBlogReview(
                book_title=book_title,
                author_name=author_name,
                confidence=confidence,
                reason=reason
            )
            
    # Fallback if AI fails or returns empty/invalid keys
    return parse_blog_review_fallback(title_clean, snippet_clean)
