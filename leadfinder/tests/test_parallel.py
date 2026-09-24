"""Tests for the bounded parallel-map used by pipeline stages."""

from __future__ import annotations

import time

import pytest

from leadfinder.services import parallel
from leadfinder.services.parallel import HostRateLimiter, map_parallel


def test_map_parallel_preserves_order_sequential(db):
    # In-memory test DB -> sequential fallback, order preserved.
    assert map_parallel(lambda x: x * 2, [1, 2, 3, 4]) == [2, 4, 6, 8]


def test_map_parallel_empty_input():
    assert map_parallel(lambda x: x, []) == []


def test_map_parallel_threaded_preserves_order_and_is_faster(db, monkeypatch):
    monkeypatch.setattr(parallel, "parallel_db_supported", lambda: True)

    def work(item):
        # Later items finish first when truly concurrent.
        time.sleep(0.05 * (5 - item))
        return item * 10

    started = time.monotonic()
    results = map_parallel(work, [1, 2, 3, 4], max_workers=4)
    elapsed = time.monotonic() - started

    assert results == [10, 20, 30, 40]
    # Sequential would take 0.05*(4+3+2+1) = 0.5s; threaded should be ~0.2s.
    assert elapsed < 0.4


def test_map_parallel_raises_first_error_after_settling(db, monkeypatch):
    monkeypatch.setattr(parallel, "parallel_db_supported", lambda: True)

    def work(item):
        if item == 2:
            raise ValueError("boom")
        return item

    with pytest.raises(ValueError, match="boom"):
        map_parallel(work, [1, 2, 3], max_workers=3)


def test_host_rate_limiter_returns_same_lock_per_host():
    limiter = HostRateLimiter()
    lock_a = limiter.lock_for("example.com")
    lock_b = limiter.lock_for("example.com")
    lock_c = limiter.lock_for("other.com")
    assert lock_a is lock_b
    assert lock_a is not lock_c
