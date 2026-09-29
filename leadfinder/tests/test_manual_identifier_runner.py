from __future__ import annotations

import pytest

from leadfinder.models import Book, Lead, ResearchRun
from leadfinder.services.pipeline.run_research import run_research_pipeline


@pytest.mark.django_db
def test_manual_asin_without_exact_book_evidence_fails_before_author_enrichment(monkeypatch):
    run = ResearchRun.objects.create(
        keyword="ISBN Search: B0TEST0001",
        source_provider="manual",
        max_books=1,
        settings_json={"run_video_search": False, "run_groq_ai_extraction": False},
    )
    book = Book.objects.create(
        research_run=run,
        title="Book for ASIN B0TEST0001",
        asin="B0TEST0001",
        normalized_key="b0test0001",
        source_provider="manual",
        source_raw_json={"processing_status": "pending"},
    )
    monkeypatch.setattr(
        "leadfinder.services.amazon.amazon_scraper.fallback_amazon_book_page",
        lambda *args, **kwargs: {"title": "", "authors": []},
    )

    run_research_pipeline(run.id)

    book.refresh_from_db()
    run.refresh_from_db()
    assert run.status == "completed"
    assert book.source_raw_json["processing_status"] == "failed"
    assert book.source_raw_json["processing_stage"] == "Needs a valid evidence match"
    assert "No exact public book metadata" in book.source_raw_json["processing_detail"]
    assert not Lead.objects.filter(book=book).exists()
