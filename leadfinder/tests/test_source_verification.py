from __future__ import annotations

import pytest

from leadfinder.models import Book, ResearchRun
from leadfinder.services.pipeline.process_book import (
    classify_result_url,
    _filter_socials_for_identity,
    _trusted_author_site_url,
)
from leadfinder.utils.normalize import normalized_book_key


@pytest.fixture
def book(db):
    run = ResearchRun.objects.create(keyword="children picture book", source_provider="csv")
    return Book.objects.create(
        research_run=run,
        title="The Bunker Visuals Story",
        author_name="Mayra Alejandra",
        normalized_key=normalized_book_key("The Bunker Visuals Story", "Mayra Alejandra", ""),
        source_provider="csv",
    )


def test_marketplace_url_is_not_trusted_as_official_author_site(book):
    assert not _trusted_author_site_url(
        "https://hotmart.com/en/marketplace/products/example",
        book,
        "The Bunker Visuals Story by Mayra Alejandra",
    )


def test_author_matching_url_can_be_trusted(book, monkeypatch):
    monkeypatch.setattr("leadfinder.services.pipeline.process_book.is_safe_public_url", lambda url: True)

    assert _trusted_author_site_url("https://mayraalejandra.com/contact", book, "Mayra Alejandra")


def test_corporate_social_profiles_are_filtered_from_author_audit(book):
    socials = {
        "instagram_url": "https://www.instagram.com/hotmart.en",
        "facebook_url": "https://www.facebook.com/hotmart.en",
        "youtube_url": "https://youtube.com/hotmarthelpcenter",
        "linkedin_url": "https://www.linkedin.com/in/mayraalejandra",
    }

    assert _filter_socials_for_identity(socials, book) == {
        "linkedin_url": "https://www.linkedin.com/in/mayraalejandra"
    }


def test_newly_untrusted_aggregators_are_not_trusted(book):
    assert not _trusted_author_site_url(
        "https://www.infobooks.org/free-pdf-books/example",
        book,
        "The Bunker Visuals Story by Mayra Alejandra",
    )
    assert not _trusted_author_site_url(
        "https://www.spokeo.com/search?q=Mayra+Alejandra",
        book,
        "Mayra Alejandra Search Result",
    )


def test_library_and_bookstore_pages_are_not_contact_or_publisher_sources(book):
    assert classify_result_url("https://openlibrary.org/about") == ("unrelated", 0.2)
    assert classify_result_url("https://mitpressbookstore.mit.edu/book/9781797227658") == ("unrelated", 0.2)


def test_blacklisted_author_words():
    from leadfinder.utils.normalize import is_valid_author_name
    assert not is_valid_author_name("Hotmart Marketplace")
    assert not is_valid_author_name("Infobooks PDF Aggregator")
    assert is_valid_author_name("Mayra Alejandra")


def test_contact_result_matches_book_or_author(book):
    from leadfinder.services.pipeline.process_book import _contact_result_matches_book_or_author
    
    class MockDTO:
        def __init__(self, title, snippet):
            self.title = title
            self.snippet = snippet

    # Book initially has title="The Bunker Visuals Story" and author_name="Mayra Alejandra"
    
    # 1. Matching author name completely (Strategy A)
    dto1 = MockDTO("Mayra Alejandra Website", "Official site of children's author Mayra Alejandra.")
    assert _contact_result_matches_book_or_author(dto1, book)
    
    # 2. Matching author last name + book title (Strategy B)
    dto2 = MockDTO("The Bunker Visuals Story", "A wonderful children's book written by Alejandra.")
    assert _contact_result_matches_book_or_author(dto2, book)
    
    # 3. Matching short name tokens (e.g. Joy)
    # Let's assign a short author name to verify it handles short names (length >= 3)
    book.author_name = "Joy Chen"
    book.title = "Zebra Forest"
    
    dto3 = MockDTO("Joy Chen Official Home", "Author Joy Chen's official contact page.")
    assert _contact_result_matches_book_or_author(dto3, book)
    
    # 4. Mismatched book and author name
    dto4 = MockDTO("John Smith Official Website", "Official site of children's author John Smith.")
    assert not _contact_result_matches_book_or_author(dto4, book)


def test_first_name_only_domain_match_is_not_trusted(db, monkeypatch):
    from leadfinder.services.pipeline.process_book import _contact_result_matches_book_or_author

    run = ResearchRun.objects.create(keyword="children picture book", source_provider="csv")
    eve_book = Book.objects.create(
        research_run=run,
        title="How to Write a Children's Picture Book",
        author_name="Eve Heidi Bine-Stock",
        normalized_key=normalized_book_key("How to Write a Children's Picture Book", "Eve Heidi Bine-Stock", ""),
        source_provider="csv",
    )

    class MockDTO:
        url = "https://store.epicgames.com/p/eve-online"
        title = "EVE Online"
        snippet = "Play the space MMO."

    monkeypatch.setattr("leadfinder.services.pipeline.process_book.is_safe_public_url", lambda url: True)

    assert not _trusted_author_site_url(MockDTO.url, eve_book, MockDTO.title)
    assert not _contact_result_matches_book_or_author(MockDTO(), eve_book)


def test_search_snippet_contact_must_match_author_or_trusted_source(book, monkeypatch):
    from leadfinder.services.pipeline.process_book import _extract_public_contact_from_search_result

    class MockDTO:
        url = "https://example.com/books/the-bunker-visuals-story"
        title = "The Bunker Visuals Story by Mayra Alejandra"
        snippet = "For unrelated services email randomsupport@gmail.com."

    monkeypatch.setattr("leadfinder.services.pipeline.process_book.is_safe_public_url", lambda url: True)
    monkeypatch.setattr("leadfinder.services.pipeline.process_book.is_highly_valid_contact_email", lambda email: True)

    assert _extract_public_contact_from_search_result(MockDTO(), "web_search_result", book) == []


def test_openlibrary_contact_source_never_verifies_lead(db):
    from leadfinder.models import AuthorProfile, Book, Evidence, Lead, ResearchRun
    from leadfinder.services.pipeline.quality_gate import has_verified_contact_source

    run = ResearchRun.objects.create(keyword="children picture book", source_provider="csv")
    bad_book = Book.objects.create(
        research_run=run,
        title="Children's Book Illustration: Step",
        author_name="Step Techniques",
        normalized_key=normalized_book_key("Children's Book Illustration: Step", "Step Techniques", "2880463351"),
        source_provider="csv",
    )
    author = AuthorProfile.objects.create(
        author_name="Step Techniques",
        normalized_author_key="step techniques",
        canonical_website="https://openlibrary.org/works/OL5120012W/Children",
        identity_confidence=0.9,
    )
    bad_lead = Lead.objects.create(book=bad_book, author_profile=author, public_email="openlibrary@archive.org")
    Evidence.objects.create(
        lead=bad_lead,
        field_name="public_email",
        field_value="openlibrary@archive.org",
        evidence_type="contact_page",
        source_url="https://openlibrary.org/about",
        confidence=0.9,
    )

    assert not has_verified_contact_source(bad_lead, "public_email", "openlibrary@archive.org")
