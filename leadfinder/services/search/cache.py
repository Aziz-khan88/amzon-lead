from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import asdict
from pathlib import Path

from django.conf import settings

from .base import SearchProvider, SearchResultDTO


_LOCK = threading.RLock()
_MEMORY_CACHE: dict[str, tuple[float, list[SearchResultDTO]]] = {}
_DISK_CACHE: dict[str, dict] | None = None
MAX_DISK_ENTRIES = 5000


def _cache_path() -> Path:
    return Path(settings.BASE_DIR) / ".cache" / "search_results.json"


def _cache_seconds() -> int:
    return max(0, int(getattr(settings, "APP_SEARCH_CACHE_SECONDS", 6 * 60 * 60)))


def _cache_key(provider_name: str, query: str, max_results: int) -> str:
    raw = json.dumps([provider_name, query, max_results], ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_disk_cache() -> dict[str, dict]:
    global _DISK_CACHE
    if _DISK_CACHE is not None:
        return _DISK_CACHE
    path = _cache_path()
    if not path.exists():
        _DISK_CACHE = {}
        return _DISK_CACHE
    try:
        _DISK_CACHE = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _DISK_CACHE = {}
    return _DISK_CACHE


def _save_disk_cache(cache: dict[str, dict]) -> None:
    # Prune expired entries and cap the file at the newest MAX_DISK_ENTRIES so
    # long-running installs never grow an unbounded, slow-to-rewrite cache file.
    ttl = _cache_seconds()
    now = time.time()
    pruned = {key: item for key, item in cache.items() if now - float(item.get("created_at", 0)) <= ttl}
    if len(pruned) > MAX_DISK_ENTRIES:
        pruned = dict(
            sorted(pruned.items(), key=lambda kv: float(kv[1].get("created_at", 0)))[-MAX_DISK_ENTRIES:]
        )
    cache.clear()
    cache.update(pruned)
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=True), encoding="utf-8")
    tmp.replace(path)


def _dto_from_dict(item: dict) -> SearchResultDTO:
    return SearchResultDTO(
        title=item.get("title") or "",
        url=item.get("url") or "",
        snippet=item.get("snippet") or "",
        rank=int(item.get("rank") or 0),
        provider=item.get("provider") or "",
    )


class CachedSearchProvider(SearchProvider):
    def __init__(self, inner: SearchProvider) -> None:
        self.inner = inner
        self.provider_name = inner.provider_name

    def search(self, query: str, max_results: int = 10) -> list[SearchResultDTO]:
        ttl = _cache_seconds()
        if ttl <= 0:
            return self.inner.search(query, max_results)

        key = _cache_key(self.provider_name, query, max_results)
        now = time.time()

        with _LOCK:
            memory_hit = _MEMORY_CACHE.get(key)
            if memory_hit and now - memory_hit[0] <= ttl:
                return list(memory_hit[1])

            disk = _load_disk_cache()
            disk_hit = disk.get(key)
            if disk_hit and now - float(disk_hit.get("created_at", 0)) <= ttl:
                results = [_dto_from_dict(item) for item in disk_hit.get("results", [])]
                _MEMORY_CACHE[key] = (float(disk_hit.get("created_at", now)), results)
                return list(results)

        results = self.inner.search(query, max_results)

        with _LOCK:
            _MEMORY_CACHE[key] = (now, list(results))
            if len(_MEMORY_CACHE) > MAX_DISK_ENTRIES:
                for old_key, _ in sorted(_MEMORY_CACHE.items(), key=lambda kv: kv[1][0])[: len(_MEMORY_CACHE) - MAX_DISK_ENTRIES]:
                    _MEMORY_CACHE.pop(old_key, None)
            disk = _load_disk_cache()
            disk[key] = {
                "created_at": now,
                "provider": self.provider_name,
                "query": query,
                "max_results": max_results,
                "results": [asdict(result) for result in results],
            }
            try:
                _save_disk_cache(disk)
            except Exception:
                pass

        return results

