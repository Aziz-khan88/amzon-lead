from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class VideoSearchResultDTO:
    title: str
    url: str
    snippet: str
    channel_name: str = ""
    published_at: str = ""
    provider: str = "youtube_api"


def search_youtube_api(query: str, max_results: int = 5) -> list[VideoSearchResultDTO]:
    api_key = os.getenv("YOUTUBE_API_KEY", "")
    if not api_key:
        return []
    try:
        from googleapiclient.discovery import build
    except Exception:
        return []
    try:
        service = build("youtube", "v3", developerKey=api_key, cache_discovery=False)
        response = (
            service.search()
            .list(q=query, part="snippet", type="video", maxResults=max_results, safeSearch="moderate")
            .execute()
        )
    except Exception:
        return []
    results: list[VideoSearchResultDTO] = []
    for item in response.get("items", []):
        video_id = item.get("id", {}).get("videoId")
        snippet = item.get("snippet", {})
        if not video_id:
            continue
        results.append(
            VideoSearchResultDTO(
                title=snippet.get("title") or "",
                url=f"https://www.youtube.com/watch?v={video_id}",
                snippet=snippet.get("description") or "",
                channel_name=snippet.get("channelTitle") or "",
                published_at=snippet.get("publishedAt") or "",
            )
        )
    return results
