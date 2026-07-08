import pytest
from unittest.mock import MagicMock
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

class MockResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code

def test_scrape_amazon_book_page_success(monkeypatch):
    html_content = b"""
    <html>
        <head><title>Test Book</title></head>
        <body>
            <span id="productTitle">The Magic Cloud</span>
            <div id="bylineInfo">
                <a href="/author/Trudy-Ludwig">Trudy Ludwig</a>
            </div>
            <span class="a-icon-alt">4.8 out of 5 stars</span>
            <span id="acrCustomerReviewText">120 reviews</span>
            <div id="bookDescription_feature_div">
                <div class="a-expander-content">A wonderful picture book.</div>
            </div>
            <img id="imgBlkFront" src="https://images.amazon.com/cover.jpg" />
            <div id="detailBullets_feature_div">
                <ul>
                    <li>Publisher : Knopf Books (September 2020)</li>
                </ul>
            </div>
        </body>
    </html>
    """
    monkeypatch.setattr("requests.get", lambda url, headers, timeout: MockResponse(html_content))

    data = scrape_amazon_book_page("B012345678", use_ai=False)
    assert data["scraped_successfully"] is True
    assert data["title"] == "The Magic Cloud"
    assert len(data["authors"]) == 1
    assert data["authors"][0]["name"] == "Trudy Ludwig"
    assert data["authors"][0]["url"] == "https://www.amazon.com/author/Trudy-Ludwig"
    assert data["rating"] == 4.8
    assert data["review_count"] == 120
    assert data["cover_image_url"] == "https://images.amazon.com/cover.jpg"
    assert "Knopf Books" in data["publisher"]
    assert "September 2020" in data["publication_date"]
    assert "wonderful picture book" in data["description"]

def test_scrape_amazon_author_page_success(monkeypatch):
    html_content = b"""
    <html>
        <head><title>Trudy Ludwig Amazon Author Profile</title></head>
        <body>
            <span id="authorBio">Trudy Ludwig is an award-winning children's author.</span>
            <img id="ap-author-image" src="https://images.amazon.com/trudy.jpg" />
            <div class="ap-book-card">The Invisible Boy</div>
            <div class="ap-book-card">My Secret Bully</div>
        </body>
    </html>
    """
    monkeypatch.setattr("requests.get", lambda url, headers, timeout: MockResponse(html_content))

    data = scrape_amazon_author_page("Trudy-Ludwig", use_ai=False)
    assert data["scraped_successfully"] is True
    assert "award-winning children's author" in data["author_bio"]
    assert data["author_image_url"] == "https://images.amazon.com/trudy.jpg"
    assert "The Invisible Boy" in data["other_books"]
    assert "My Secret Bully" in data["other_books"]

@pytest.mark.django_db
def test_pipeline_integration_with_scraped_data(monkeypatch):
    # Mock book page
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
    
    # Mock author page
    def mock_scrape_author(url, use_ai=True):
        return {
            "amazon_author_url": url,
            "author_bio": "Mock Biography of the kids book author.",
            "author_image_url": "https://mock.author.jpg",
            "other_books": ["Mock Other Book 1", "Mock Other Book 2"],
            "scraped_successfully": True,
        }

    monkeypatch.setattr("leadfinder.services.amazon.amazon_scraper.scrape_amazon_book_page", mock_scrape_book)
    monkeypatch.setattr("leadfinder.services.amazon.amazon_scraper.scrape_amazon_author_page", mock_scrape_author)
    
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
    assert author.author_bio == "Mock Biography of the kids book author."
    assert author.author_image_url == "https://mock.author.jpg"
    assert len(author.other_books) == 2
    assert "Mock Other Book 1" in author.other_books
    
    # Assert evidence was stored
    evidences = Evidence.objects.filter(lead=lead)
    assert evidences.filter(evidence_type="amazon_search_result").exists()
    assert evidences.filter(field_name="amazon_author_url").exists()


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
