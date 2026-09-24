"""Deterministic per-host proxy rotation for outbound crawl requests.

Set ``APP_PROXY_LIST=http://user:pass@host:port,socks5://host:port,...`` to
spread crawl traffic across egress proxies.  The same host always uses the
same proxy (stable cookies/rate-limits upstream) while different hosts rotate
across the pool.  Empty list = direct connections, exactly as before.
"""

from __future__ import annotations

import hashlib

from django.conf import settings


def proxy_pool() -> list[str]:
    raw = getattr(settings, "APP_PROXY_LIST", "") or ""
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


def proxies_for_url(url: str) -> dict | None:
    """Return a ``requests`` proxies dict for ``url``, or None for direct."""

    pool = proxy_pool()
    if not pool:
        return None
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    index = int(hashlib.sha256(host.encode("utf-8")).hexdigest(), 16) % len(pool)
    proxy = pool[index]
    return {"http": proxy, "https": proxy}
