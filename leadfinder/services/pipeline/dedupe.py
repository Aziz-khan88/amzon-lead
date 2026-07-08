from __future__ import annotations

from leadfinder.utils.normalize import normalized_book_key


def dedupe_book_candidates(candidates: list[dict]) -> list[dict]:
    seen_asins: set[str] = set()
    seen_keys: set[str] = set()
    unique: list[dict] = []
    for candidate in candidates:
        asin = (candidate.get("asin") or "").upper()
        if asin:
            if asin in seen_asins:
                continue
            seen_asins.add(asin)
        key = normalized_book_key(candidate.get("title"), candidate.get("author_name"), asin)
        if not asin and key in seen_keys:
            continue
        seen_keys.add(key)
        unique.append(candidate)
    return unique
