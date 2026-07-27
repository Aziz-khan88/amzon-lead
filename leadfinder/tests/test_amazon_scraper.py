import pytest
from leadfinder.services.amazon.amazon_scraper import (
    scrape_amazon_book_page,
    scrape_amazon_author_page,
    extract_rating,
    extract_review_count,
)
from leadfinder.services.pipeline.process_book import process_book
from leadfinder.models import ResearchRun, Book, AuthorProfile, Lead, Evidence

def test_extract_rating():
    assert extract_rating("4.8 out of 5 stars") == 4.8
    assert extract_rating("Rating: 4.5 Stars") == 4.5
    assert extract_rating("3 stars") == 3.0
    assert extract_rating("no rating") is None

def test_extract_review_count():
    assert extract_review_count("1,234 ratings") == 1234
    assert extract_review_count("45 reviews") == 45
    assert extract_review_count("no reviews") is None

def test_scrape_amazon_book_page_success(monkeypatch):
    def fail_direct_request(*args, **kwargs):
        raise AssertionError("Amazon product pages must not be requested directly")

    monkeypatch.setattr("requests.get", fail_direct_request)
    monkeypatch.setattr(
        "leadfinder.services.amazon.amazon_scraper.fallback_amazon_book_page",
        lambda *args, **kwargs: {
            "title": "The Magic Cloud",
            "authors": [{"name": "Trudy Ludwig", "url": ""}],
            "rating": 4.8,
            "review_count": 120,
            "cover_image_url": "https://images.example/cover.jpg",
            "publisher": "Knopf Books",
            "publication_date": "September 2020",
            "description": "A wonderful picture book.",
            "scraped_successfully": True,
        },
    )

    data = scrape_amazon_book_page("B012345678", use_ai=False)
    assert data["scraped_successfully"] is True
    assert data["title"] == "The Magic Cloud"
    assert len(data["authors"]) == 1
    assert data["authors"][0]["name"] == "Trudy Ludwig"
    assert data["direct_amazon_fetch"] is False
    assert data["rating"] == 4.8
    assert data["review_count"] == 120
    assert data["cover_image_url"] == "https://images.example/cover.jpg"
    assert "Knopf Books" in data["publisher"]
    assert "September 2020" in data["publication_date"]
    assert "wonderful picture book" in data["description"]

def test_scrape_amazon_author_page_success(monkeypatch):
    monkeypatch.setattr("requests.get", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("No direct fetch")))

    data = scrape_amazon_author_page("Trudy-Ludwig", use_ai=False)
    assert data["scraped_successfully"] is False
    assert data["author_bio"] == ""
    assert "disabled" in data["warnings"][0].lower()

@pytest.mark.django_db
def test_pipeline_integration_with_public_search_data(monkeypatch):
    # Mock source-backed public search enrichment. The pipeline intentionally
    # does not request Amazon product or author pages directly.
    def mock_scrape_book(asin, use_ai=True, book_title=""):
        return {
            "asin": asin,
            "title": "Mock Book Title",
            "authors": [{"name": "Mock Author", "url": "https://www.amazon.com/author/mock-author"}],
            "rating": 4.9,
            "review_count": 999,
            "publisher": "Mock Press",
            "publication_date": "January 2025",
            "cover_image_url": "https://mock.image.jpg",
            "description": "Mock description of the children picture book",
            "scraped_successfully": True,
            "source": f"https://www.amazon.com/dp/{asin}",
        }
    
    monkeypatch.setattr("leadfinder.services.amazon.amazon_scraper.fallback_amazon_book_page", mock_scrape_book)
    
    # Disable video search and groq ai to keep it fast
    monkeypatch.setattr("leadfinder.services.pipeline.process_book.search_youtube_api", lambda *args, **kwargs: [])
    
    class FakeClassification:
        is_childrens_book = True
        is_picture_or_illustrated_book = True
        confidence = 0.95
        reason = "Mock reason"
    
    monkeypatch.setattr("leadfinder.services.pipeline.process_book.classify_book", lambda *args, **kwargs: FakeClassification())
    
    class FakeExtraction:
        canonical_website = "https://mockauthor.com"
        contact_page_url = "https://mockauthor.com/contact"
        publisher_url = ""
        instagram_url = ""
        facebook_url = ""
        tiktok_url = ""
        youtube_url = ""
        linkedin_url = ""
        goodreads_url = ""
        location = "California"
        agent_name = ""
        representation_email = ""
        publicist_email = ""
        confidence = 0.9
        public_email = "author@mockauthor.com"
        public_phone = ""
        evidence = []
        warnings = []
        
    monkeypatch.setattr("leadfinder.services.pipeline.process_book.extract_contact_data", lambda *args, **kwargs: FakeExtraction())
    
    # Fake search results to prevent actual web queries
    class FakeSearchProvider:
        provider_name = "mock_search"
        def search(self, *args, **kwargs):
            return []
            
    monkeypatch.setattr("leadfinder.services.pipeline.process_book.get_search_provider", lambda *args, **kwargs: FakeSearchProvider())

    run = ResearchRun.objects.create(keyword="kids book", source_provider="ddgs")
    book = Book.objects.create(
        research_run=run,
        title="Original Title",
        author_name="",
        asin="B012345678",
        normalized_key="original_title_key",
        source_provider="ddgs",
    )
    
    lead = process_book(book, run_video_search=False, run_ai_extraction=False)
    
    # Assert book enrichment
    book.refresh_from_db()
    assert book.title == "Mock Book Title"
    assert book.author_name == "Mock Author"
    assert float(book.rating) == 4.9
    assert book.review_count == 999
    assert book.publisher == "Mock Press"
    assert book.publication_date == "January 2025"
    assert book.cover_image_url == "https://mock.image.jpg"
    assert book.is_childrens_book is True
    assert book.is_picture_or_illustrated_book is True
    
    # Assert author profile details
    author = lead.author_profile
    assert author.author_name == "Mock Author"
    assert author.amazon_author_url == "https://www.amazon.com/author/mock-author"
    assert author.author_bio == ""
    assert author.author_image_url == ""
    assert author.other_books == []
    
    # Assert evidence was stored
    evidences = Evidence.objects.filter(lead=lead)
    assert evidences.filter(field_name="amazon_author_url").exists()
    assert evidences.filter(field_name="canonical_website", source_url="https://mockauthor.com").exists()


def test_fallback_amazon_book_page_asin_catalog(monkeypatch):
    class MockSearchResultDTO:
        def __init__(self, title, url, snippet):
            self.title = title
            self.url = url
            self.snippet = snippet
            self.provider = "mock"
            self.rank = 1

    class FakeSearchProvider:
        provider_name = "mock"
        def search(self, query, max_results=3):
            if "site:amazon.com" in query:
                # Return empty or useless amazon result
                return [MockSearchResultDTO("Amazon.com: Books", "https://www.amazon.com/dp/B0DQ1YHSZX", "No author details here")]
            elif "B0DQ1YHSZX" in query:
                # Attempt 2: global search with ASIN returns a Goodreads result
                return [
                    MockSearchResultDTO(
                        "Children of Time Series 3 Books Set by Adrian Tchaikovsky | Goodreads",
                        "https://www.goodreads.com/book/show/123456.Children_of_Time_Series_3_Books_Set",
                        "Children of Time Series 3 Books Set includes Children of Time, Children of Ruin, Children of Memory. Published December 10, 2024 by Adrian Tchaikovsky."
                    )
                ]
            return []

    monkeypatch.setattr("leadfinder.services.amazon.amazon_scraper.get_search_provider", lambda *args, **kwargs: FakeSearchProvider())
    monkeypatch.setattr("leadfinder.services.ai.groq_client.GroqJSONClient.available", False)

    from leadfinder.services.amazon.amazon_scraper import fallback_amazon_book_page
    data = fallback_amazon_book_page("B0DQ1YHSZX", use_ai=False, book_title="Children of Time Series 3 Books Set")
    
    assert len(data["authors"]) == 1
    assert data["authors"][0]["name"] == "Adrian Tchaikovsky"


def test_fallback_amazon_book_page_title_author_query(monkeypatch):
    class MockSearchResultDTO:
        def __init__(self, title, url, snippet):
            self.title = title
            self.url = url
            self.snippet = snippet
            self.provider = "mock"
            self.rank = 1

    class FakeSearchProvider:
        provider_name = "mock"
        def search(self, query, max_results=3):
            if "site:amazon.com" in query or "B0DQ1YHSZX" in query:
                return []
            elif "Children of Time" in query and "author" in query:
                # Attempt 3: book title + author search
                return [
                    MockSearchResultDTO(
                        "Adrian Tchaikovsky - Wikipedia",
                        "https://en.wikipedia.org/wiki/Adrian_Tchaikovsky",
                        "Adrian Tchaikovsky is a British fantasy and science fiction author, best known for his series Children of Time."
                    )
                ]
            return []

    monkeypatch.setattr("leadfinder.services.amazon.amazon_scraper.get_search_provider", lambda *args, **kwargs: FakeSearchProvider())
    monkeypatch.setattr("leadfinder.services.ai.groq_client.GroqJSONClient.available", False)

    from leadfinder.services.amazon.amazon_scraper import fallback_amazon_book_page
    data = fallback_amazon_book_page("B0DQ1YHSZX", use_ai=False, book_title="Children of Time Series 3 Books Set")
    
    assert len(data["authors"]) == 1
    assert data["authors"][0]["name"] == "Adrian Tchaikovsky"
