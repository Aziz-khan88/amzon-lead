from __future__ import annotations

from leadfinder.models import Evidence, SalesAgentBrief, SearchQueryLog, VideoEvidence
from leadfinder.services.ai.classify_video import choose_video_status, classify_video
from leadfinder.services.ai.summarize_sales_brief import render_brief_markdown, summarize_sales_brief
from leadfinder.services.search import get_search_provider
from leadfinder.services.search.video_provider import search_youtube_api


def _video_queries(lead) -> list[str]:
    book = lead.book
    return [
        f'"{book.title}" "{book.author_name}" book trailer',
        f'"{book.title}" "{book.author_name}" animated trailer',
        f'"{book.title}" "{book.author_name}" read aloud',
    ]


def _save_video(lead, data: dict, source_provider: str, use_ai: bool):
    classification = classify_video(data, use_ai=use_ai)
    if not VideoEvidence.objects.filter(lead=lead, video_url=data["video_url"]).exists():
        VideoEvidence.objects.create(
            lead=lead,
            video_url=data["video_url"],
            title=data["title"][:500],
            channel_name=data.get("channel_name", "")[:255],
            description=data.get("description", ""),
            published_at=data.get("published_at", ""),
            source_provider=source_provider,
            matches_book=classification.matches_book,
            matches_author=classification.matches_author,
            is_book_trailer=classification.is_book_trailer,
            is_animated_video=classification.is_animated_video,
            is_read_aloud=classification.is_read_aloud,
            is_author_interview=classification.is_author_interview,
            classification_confidence=classification.confidence,
            classification_reason=classification.reason,
        )
    if not Evidence.objects.filter(lead=lead, field_name="video_evidence_url", field_value=data["video_url"]).exists():
        Evidence.objects.create(
            lead=lead,
            book=lead.book,
            evidence_type="youtube_result" if "youtu" in data["video_url"].lower() else "vimeo_result",
            field_name="video_evidence_url",
            field_value=data["video_url"],
            source_url=data["video_url"],
            source_title=data["title"][:500],
            source_snippet=data.get("description", ""),
            confidence=classification.confidence,
        )
    return classification


def check_imported_lead_videos(lead, *, use_ai: bool = False) -> None:
    """Run the video checker without replacing manually imported lead data."""
    provider_name = (lead.book.research_run.settings_json or {}).get("enrichment_provider")
    provider = get_search_provider(provider_name)
    classifications = []
    for query in _video_queries(lead):
        try:
            youtube_results = search_youtube_api(query, max_results=5)
            for item in youtube_results:
                classifications.append(
                    _save_video(
                        lead,
                        {
                            "book_title": lead.book.title,
                            "author_name": lead.book.author_name,
                            "title": item.title,
                            "video_url": item.url,
                            "description": item.snippet or "",
                            "channel_name": item.channel_name,
                            "published_at": item.published_at,
                        },
                        "youtube_api",
                        use_ai,
                    )
                )
            if youtube_results:
                continue
            search_query = f"site:youtube.com OR site:vimeo.com {query}"
            log = SearchQueryLog.objects.create(
                research_run=lead.book.research_run,
                book=lead.book,
                query=search_query,
                provider=provider.provider_name,
            )
            results = provider.search(search_query, max_results=5)
            log.result_count = len(results)
            log.save(update_fields=["result_count"])
            for item in results:
                if not any(host in item.url.lower() for host in ("youtube.", "youtu.be", "vimeo.")):
                    continue
                classifications.append(
                    _save_video(
                        lead,
                        {
                            "book_title": lead.book.title,
                            "author_name": lead.book.author_name,
                            "title": item.title,
                            "video_url": item.url,
                            "description": item.snippet or "",
                        },
                        "web_search",
                        use_ai,
                    )
                )
        except Exception:
            continue
    lead.video_status, lead.video_confidence, _ = choose_video_status(classifications, search_completed=True)
    lead.save(update_fields=["video_status", "video_confidence", "updated_at"])


def build_imported_sales_brief(lead, *, use_ai: bool) -> None:
    book = lead.book
    author = lead.author_profile
    payload = {
        "book": {
            "title": book.title,
            "author_name": book.author_name,
            "amazon_book_url": book.amazon_book_url,
            "asin": book.asin,
            "category": book.category,
            "publisher": book.publisher,
        },
        "author": {"author_name": author.author_name if author else book.author_name, "website": author.canonical_website if author else ""},
        "contact": {"email": lead.public_email, "phone": lead.public_phone},
        "video_status": lead.video_status,
        "missing_data": lead.missing_data_json,
        "warnings": lead.warnings_json,
    }
    summary = summarize_sales_brief(payload, use_ai=use_ai)
    for field in (
        "sales_agent_summary",
        "fit_reason",
        "suggested_pitch_angle",
        "suggested_first_line",
        "what_to_say",
        "what_not_to_say",
        "next_best_action",
    ):
        setattr(lead, field, summary.get(field, getattr(lead, field)))
    lead.save(update_fields=[
        "sales_agent_summary", "fit_reason", "suggested_pitch_angle", "suggested_first_line", "what_to_say",
        "what_not_to_say", "next_best_action", "updated_at",
    ])
    source_links = list(lead.evidence.exclude(source_url="").values_list("source_url", flat=True).distinct())
    SalesAgentBrief.objects.update_or_create(
        lead=lead,
        defaults={
            "brief_markdown": render_brief_markdown(lead, source_links),
            "outreach_angle": lead.suggested_pitch_angle,
            "objection_notes": lead.what_not_to_say,
            "pitch_direct": summary.get("pitch_direct", ""),
            "pitch_agent": summary.get("pitch_agent", ""),
            "pitch_publicist": summary.get("pitch_publicist", ""),
            "source_links_json": source_links,
        },
    )
