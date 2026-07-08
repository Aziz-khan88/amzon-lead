from __future__ import annotations

import re
import unicodedata


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalized_book_key(title: str | None, author: str | None, asin: str | None = None) -> str:
    if asin:
        return f"asin:{asin.upper()}"
    return f"{normalize_text(title)}::{normalize_text(author)}"


def normalized_author_key(author: str | None) -> str:
    return normalize_text(author)


def clean_title_from_search(title: str) -> str:
    title = re.sub(r"\s*[:|-]\s*Amazon\..*$", "", title, flags=re.I)
    title = re.sub(r"\s*[:|-]\s*Amazon.*$", "", title, flags=re.I)
    title = re.sub(r"\s*\([^)]*Paperback[^)]*\)", "", title, flags=re.I)
    return title.strip(" -:|")


BLACK_LISTED_AUTHOR_WORDS = {
    "step", "techniques",
    "paperback", "hardcover", "edition", "ages", "years", "amazon", "stars", "rating", "review",
    "reviews", "publisher", "published", "today", "scholastic", "instructor", "presentations",
    "empower", "perfection", "robot", "island", "introduction", "foreword", "contributor",
    "editor", "reader", "series", "volume", "vol", "illustrated",
    "perfect", "successful", "successfully",
    "sells", "publishers", "readers", "classic", "stories", "treasury", "treasuries", "complete",
    "learning", "learn",
    "hotmart", "infobooks", "pdfdrive", "epub", "spokeo", "whitepages", "radaris", "beenverified",
    "truthfinder", "intelius", "peoplefinders", "anyflip", "fliphtml5", "scribd", "slideshare",
    "issuu", "target", "walmart", "linktree"
}


def clean_author_name(name: str) -> str:
    """
    Cleans an author name candidate.
    - Strips leading/trailing junk and common noise prefixes.
    - Truncates the candidate before any blacklisted/junk word.
    """
    if not name:
        return ""
    
    # Remove ellipses
    name = re.sub(r"\.\.\.", "", name).strip()
    
    # Remove common prefix/suffix noise
    name = re.sub(r"-\s*Amazon\.com", "", name, flags=re.I)
    name = re.sub(r"Amazon\.com", "", name, flags=re.I)
    name = re.sub(r"Visit\s+Amazon's\s+", "", name, flags=re.I)
    name = re.sub(r"\s+Page", "", name, flags=re.I)
    name = re.sub(r"Search\s+results\s+for\s+", "", name, flags=re.I)
    name = re.sub(r"acclaimed\s+illustrator\s+", "", name, flags=re.I)
    name = re.sub(r"illustrator\s+and\s+author\s+", "", name, flags=re.I)
    name = re.sub(r"author\s+and\s+illustrator\s+", "", name, flags=re.I)
    name = re.sub(r"\s*\((?:Author|Illustrator|Contributor|Editor|Writer|Translator|Artist)\)", "", name, flags=re.I)
    
    # Split into words
    words = name.split()
    cleaned_words = []
    for w in words:
        w_cleaned = w.strip(".,;:()[]\"'").lower()
        if w_cleaned in BLACK_LISTED_AUTHOR_WORDS:
            break
        cleaned_words.append(w)
        
    return " ".join(cleaned_words).strip(" ,.-:|")


def is_valid_author_name(name: str) -> bool:
    if not name or len(name) < 3 or len(name) > 60:
        return False
    words = [w.strip(".,;:()[]").lower() for w in name.split()]
    if len(words) < 2:
        return False
    if any(w in BLACK_LISTED_AUTHOR_WORDS for w in words if w):
        return False
    # Ensure there's at least one capitalized letter (not just numbers/junk)
    if not any(c.isupper() for c in name):
        # Allow normalized lower check if capitalization was lost, but usually names have letters
        if not any(c.isalpha() for c in name):
            return False
    return True


def extract_authors_from_colon_format(title: str) -> list[str]:
    """
    Extracts author names from formatted book titles like:
    "Sweet Tooth: Palatini, Margie, Davis, Jack E.: 9780689851599 ..."
    "Brave Every Day: Ludwig, Trudy, Barton, Patrice: 9780593306376 ..."
    """
    if not title:
        return []
    
    parts = [p.strip() for p in title.split(":")]
    authors = []
    
    for part in parts:
        subparts = [s.strip() for s in part.split(",")]
        i = 0
        while i < len(subparts) - 1:
            cand_last = subparts[i]
            cand_first = subparts[i+1]
            if cand_last and cand_first and cand_last[0].isupper() and cand_first[0].isupper():
                full_name = f"{cand_first} {cand_last}"
                cleaned = clean_author_name(full_name)
                if is_valid_author_name(cleaned) and cleaned not in authors:
                    authors.append(cleaned)
                i += 2
            else:
                i += 1
    return authors

