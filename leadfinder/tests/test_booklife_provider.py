from leadfinder.services.booklife.provider import BookLifeCategory, BookLifeProjectProvider
from leadfinder.services.search.base import SearchResultDTO


PROJECT_BROWSE_HTML = """
<html>
  <body>
    <ul>
      <li>
        <a href="/project/example-book-123"><img src="/covers/example.jpg">Example Book</a>
        <p>by Avery Moon</p>
        <p>A warm project summary for the card.</p>
        <a href="/project/example-book-123">more</a>
      </li>
    </ul>
    <a href="/project-browse/all/fiction-romance/2">&raquo;</a>
  </body>
</html>
"""


PROJECT_DETAIL_HTML = """
<html>
  <head><meta property="og:image" content="/covers/detail.jpg"></head>
  <body>
    <a href="https://averymoonbooks.example/contact">Official site</a>
    <a href="https://facebook.com/averymoonbooks">Facebook</a>
    <p>Avery Moon writes picture books and visits schools.</p>
  </body>
</html>
"""


REALISTIC_PROJECT_DETAIL_HTML = """
<html>
  <head>
    <meta property="og:title" content="Cincher's Waltz by Joslyn Chase | BookLife">
    <meta property="og:image" content="http://booklife.com/covers/cincher.jpg">
  </head>
  <body>
    <div class="user-profile-card">
      <a href="/profile/joslyn-chase-100" class="name">Joslyn Chase</a>
      <div class="user-profile-social">
        | <a href="https://joslynchase.com/" target="offsite">Website</a>
        | <a href="https://www.facebook.com/StoryChase" target="offsite">Facebook</a>
      </div>
    </div>
    <div class="public-project-title">Cincher's Waltz</div>
    <div class="public-project-credit"><a href="/profile/joslyn-chase-100">Joslyn Chase</a>, author</div>
    <div class="public-project-synopsis">After losing her family in a devastating fire, Riley trains to go undercover.</div>
    <footer>
      <a href="http://www.mediapolis.com">Mediapolis</a>
      <a href="http://sonyabalchandani.com/">Sonya Balchandani</a>
    </footer>
  </body>
</html>
"""


def test_booklife_project_cards_are_parsed():
    provider = BookLifeProjectProvider(fetch_project_details=False)
    category = BookLifeCategory("fiction-romance", "Romance", "Fiction")

    candidates = provider.parse_project_cards(
        PROJECT_BROWSE_HTML,
        "https://booklife.com/project-browse/all/fiction-romance",
        category,
    )

    assert len(candidates) == 1
    assert candidates[0]["title"] == "Example Book"
    assert candidates[0]["author_name"] == "Avery Moon"
    assert candidates[0]["category"] == "Romance"
    assert candidates[0]["booklife_project_url"] == "https://booklife.com/project/example-book-123"
    assert candidates[0]["cover_image_url"] == "https://booklife.com/covers/example.jpg"


def test_booklife_project_detail_collects_public_link_hints():
    provider = BookLifeProjectProvider(fetch_project_details=False)

    detail = provider.parse_project_detail(PROJECT_DETAIL_HTML, "https://booklife.com/project/example-book-123")

    assert detail["cover_image_url"] == "https://booklife.com/covers/detail.jpg"
    assert detail["booklife_social_links"]["facebook_url"] == "https://facebook.com/averymoonbooks"
    assert detail["booklife_author_urls"] == ["https://averymoonbooks.example/contact"]


def test_booklife_project_detail_uses_actual_project_sections():
    provider = BookLifeProjectProvider(fetch_project_details=False)

    detail = provider.parse_project_detail(
        REALISTIC_PROJECT_DETAIL_HTML,
        "https://booklife.com/project/cincher-s-waltz-107925",
    )

    assert detail["title"] == "Cincher's Waltz"
    assert detail["author_name"] == "Joslyn Chase"
    assert detail["booklife_author_urls"] == ["https://joslynchase.com/"]
    assert detail["booklife_social_links"]["facebook_url"] == "https://www.facebook.com/StoryChase"
    assert detail["booklife_profile_urls"] == ["https://booklife.com/profile/joslyn-chase-100"]
    assert detail["detail_text"].startswith("After losing her family")


def test_booklife_next_page_url_is_found():
    provider = BookLifeProjectProvider(fetch_project_details=False)

    next_url = provider._next_page_url(PROJECT_BROWSE_HTML, "https://booklife.com/project-browse/all/fiction-romance")

    assert next_url == "https://booklife.com/project-browse/all/fiction-romance/2"


def test_booklife_search_result_becomes_candidate():
    provider = BookLifeProjectProvider(fetch_project_details=False)
    dto = SearchResultDTO(
        title="Example Book - BookLife",
        url="https://booklife.com/project/example-book-123",
        snippet="by Avery Moon. A warm project summary for the card.",
        rank=1,
        provider="ddgs",
    )

    candidate = provider.candidate_from_search_result(dto, "fiction-romance")

    assert candidate["title"] == "Example Book"
    assert candidate["author_name"] == "Avery Moon"
    assert candidate["category"] == "Romance"
    assert candidate["source_raw_json"]["source"] == "booklife_search_index"
