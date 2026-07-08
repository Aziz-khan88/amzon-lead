from __future__ import annotations

import time

from django.conf import settings

from .base import SearchProvider, SearchResultDTO


class DDGSSearchProvider(SearchProvider):
    provider_name = "ddgs"

    def search(self, query: str, max_results: int = 10) -> list[SearchResultDTO]:
        try:
            from ddgs import DDGS
            from ddgs.exceptions import DDGSException
        except Exception:
            return []
        time.sleep(float(getattr(settings, "APP_SEARCH_DELAY_SECONDS", getattr(settings, "APP_REQUEST_DELAY_SECONDS", 0.4))))
        backend_setting = getattr(settings, "DDGS_BACKEND", "yahoo,startpage,mojeek,yandex")
        backends = [backend.strip() for backend in str(backend_setting).split(",") if backend.strip()]
        errors: list[str] = []
        for backend in backends or ["duckduckgo"]:
            try:
                raw_results = self._search_backend(DDGS, query, max_results, backend)
            except DDGSException as exc:
                message = str(exc)
                if "No results found" in message:
                    continue
                errors.append(f"{backend}: {message}")
                continue
            except Exception as exc:
                errors.append(f"{backend}: {exc}")
                continue
            results = self._to_dtos(raw_results, max_results)
            if results:
                return results
        if errors:
            raise RuntimeError("DDGS search failed: " + " | ".join(errors[:3]))
        return []

    def _search_backend(self, ddgs_cls, query: str, max_results: int, backend: str) -> list[dict]:
        try:
            with ddgs_cls(
                timeout=int(getattr(settings, "APP_REQUEST_TIMEOUT_SECONDS", 15)),
                verify=bool(getattr(settings, "DDGS_VERIFY_SSL", False)),
            ) as ddgs:
                return list(ddgs.text(query, max_results=max_results, backend=backend))
        except Exception:
            raise

    def _to_dtos(self, raw_results: list[dict], max_results: int) -> list[SearchResultDTO]:
        if not raw_results:
            return []
        results: list[SearchResultDTO] = []
        for rank, item in enumerate(raw_results[:max_results], start=1):
            url = item.get("href") or item.get("url") or ""
            if not url:
                continue
            results.append(
                SearchResultDTO(
                    title=item.get("title") or "",
                    url=url,
                    snippet=item.get("body") or item.get("snippet") or "",
                    rank=rank,
                    provider=self.provider_name,
                )
            )
        return results
