from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from leadfinder.services.ai.blog_parser import parse_blog_review_fallback, parse_blog_review
from leadfinder.services.search.base import SearchResultDTO
from leadfinder.management.commands.scrape_blog_book_leads import find_amazon_match, Command


def test_parse_blog_review_fallback_standard():
    title = "Review: The Adventures of Pip by Jane Doe | The Children's Book Review"
    snippet = "Jane Doe's fantastic new picture book The Adventures of Pip tells the rhyming story of..."
    res = parse_blog_review_fallback(title, snippet)
    
    assert res.book_title == "The Adventures of Pip"
    assert res.author_name == "Jane Doe"
    assert res.confidence > 0.5


def test_parse_blog_review_fallback_alternative():
    title = "Pip's Day by Jane Doe - Book Review"
    snippet = "Discover the new bedtime story Pip's Day by author Jane Doe..."
    res = parse_blog_review_fallback(title, snippet)
    
    assert res.book_title == "Pip's Day"
    assert res.author_name == "Jane Doe"
    assert res.confidence > 0.5


def test_parse_blog_review_fallback_failure():
    title = "10 Great Children's Books for Summer"
    snippet = "Here is our top list of illustrated stories that kids will love this season..."
    res = parse_blog_review_fallback(title, snippet)
    
    assert res.book_title is None
    assert res.author_name is None
    assert res.confidence == 0.0


def test_parse_blog_review_uses_fallback_when_no_ai():
    title = "Review of Sleepy Bunny by David Miller"
    snippet = "We review Sleepy Bunny by David Miller, a cute picture book."
    res = parse_blog_review(title, snippet, use_ai=False)
    
    assert res.book_title == "Sleepy Bunny"
    assert res.author_name == "David Miller"


def test_find_amazon_match_success():
    provider = MagicMock()
    provider.search.return_value = [
        SearchResultDTO(
            title="Amazon.com: Sleepy Bunny by David Miller",
            url="https://www.amazon.com/dp/B012345678",
            snippet="Sleepy Bunny by David Miller on Amazon",
            rank=1,
            provider="tavily"
        )
    ]
    
    match = find_amazon_match(provider, "Sleepy Bunny", "David Miller")
    assert match is not None
    url, asin = match
    assert asin == "B012345678"
    assert url == "https://www.amazon.com/dp/B012345678"


def test_find_amazon_match_fallback():
    provider = MagicMock()
    # First search returns empty list, second fallback query returns valid result
    provider.search.side_effect = [
        [],
        [
            SearchResultDTO(
                title="Sleepy Bunny: David Miller: Amazon.com",
                url="https://www.amazon.com/dp/B087654321",
                snippet="Sleepy Bunny by David Miller",
                rank=1,
                provider="tavily"
            )
        ]
    ]
    
    match = find_amazon_match(provider, "Sleepy Bunny", "David Miller")
    assert match is not None
    url, asin = match
    assert asin == "B087654321"
    assert url == "https://www.amazon.com/dp/B087654321"
