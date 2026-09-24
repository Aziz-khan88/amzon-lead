"""Bounded order-preserving parallel map for I/O-bound pipeline stages.

The pipeline is network-bound: search queries, page fetches, and video lookups
spend nearly all their time waiting on remote hosts.  Running those waits
concurrently multiplies throughput without burning CPU.

Safety rules baked in here:
- Results keep the input order, so downstream ranking/dedupe logic is stable.
- Worker functions must do network I/O only; database writes stay in the
  calling thread (each worker still closes its own stale DB connection).
- In-memory SQLite (test runs) locks out secondary connections, so the map
  silently degrades to sequential execution there.
- Global concurrency stays bounded: pipeline workers x stage workers, both
  capped by settings.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Iterable

from django.conf import settings
from django.db import close_old_connections, connection


def stage_workers() -> int:
    """Max concurrent network operations inside one pipeline stage."""
    return max(1, min(int(getattr(settings, "APP_STAGE_WORKERS", 4) or 4), 8))


def parallel_db_supported() -> bool:
    """In-memory SQLite (tests) serializes writers with hard table locks."""
    name = str(connection.settings_dict.get("NAME") or "")
    return ":memory:" not in name and "mode=memory" not in name


def map_parallel(
    func: Callable[[Any], Any],
    items: Iterable[Any],
    max_workers: int | None = None,
) -> list[Any]:
    """Apply ``func`` to every item, preserving input order.

    Exceptions raised by ``func`` propagate after all work settles (first
    error wins), matching the behavior of a sequential map.
    """
    item_list = list(items)
    if not item_list:
        return []
    workers = max_workers or stage_workers()
    workers = max(1, min(workers, len(item_list)))
    if workers == 1 or not parallel_db_supported():
        return [func(item) for item in item_list]

    def wrapped(item):
        try:
            return func(item)
        finally:
            close_old_connections()

    results: list[Any] = [None] * len(item_list)
    first_error: BaseException | None = None
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="stage") as pool:
        futures = {pool.submit(wrapped, item): index for index, item in enumerate(item_list)}
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except BaseException as exc:  # noqa: BLE001 - re-raised after settle
                if first_error is None:
                    first_error = exc
    if first_error is not None:
        raise first_error
    return results


class HostRateLimiter:
    """Serialize requests per host so parallel crawling stays polite.

    Different hosts are fetched concurrently; requests to the SAME host keep
    their configured delay between hits, honoring the spirit of robots.txt
    crawl pacing even when stages run in parallel.
    """

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def lock_for(self, host: str) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(host)
            if lock is None:
                lock = threading.Lock()
                self._locks[host] = lock
            return lock
