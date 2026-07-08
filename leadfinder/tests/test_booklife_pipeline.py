import pytest

from leadfinder.models import Book, ResearchRun, SearchQueryLog
from leadfinder.services.booklife import BookLifeRobotsBlocked
from leadfinder.services.pipeline.run_research import run_research_pipeline
from leadfinder.services.search.base import SearchResultDTO


class FakeSearchProvider:
    provider_name = "ddgs"

    def search(self, query, max_results=10):
        return [
            SearchResultDTO(
                title="Example Book - BookLife",
                url="https://booklife.com/project/example-book-123",
                snippet="by Avery Moon. A warm BookLife project summary.",
                rank=1,
                provider=self.provider_name,
            )
        ]


@pytest.mark.django_db
def test_booklife_pipeline_falls_back_to_search_index_when_robots_block(monkeypatch):
    def blocked_discovery(*args, **kwargs):
        raise BookLifeRobotsBlocked("blocked")

    def fake_process_book(book, run_video_search=True, run_ai_extraction=True):
        return None

    monkeypatch.setattr(
        "leadfinder.services.booklife.provider.BookLifeProjectProvider.discover_books",
        blocked_discovery,
    )
    monkeypatch.setattr(
        "leadfinder.services.pipeline.run_research.get_search_provider",
        lambda name=None: FakeSearchProvider(),
    )
    monkeypatch.setattr(
        "leadfinder.services.pipeline.run_research.process_book",
        fake_process_book,
    )

    run = ResearchRun.objects.create(
        keyword="BookLife: Romance",
        source_provider="booklife",
        max_books=1,
        settings_json={
            "booklife_categories": ["fiction-romance"],
            "booklife_category_labels": ["Romance"],
            "booklife_age_filter": "all",
            "enrichment_provider": "ddgs",
        },
    )

    run_research_pipeline(run.id)

    run.refresh_from_db()
    book = Book.objects.get(research_run=run)
    assert run.status == "completed"
    assert book.title == "Example Book"
    assert book.author_name == "Avery Moon"
    assert book.source_raw_json["source"] == "booklife_search_index"
    assert SearchQueryLog.objects.filter(query__icontains="search-index fallback", result_count=1).exists()
