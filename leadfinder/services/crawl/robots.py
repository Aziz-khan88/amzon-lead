from __future__ import annotations

import threading
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

# Cache parsed robots.txt per host so we fetch it once per host per TTL window
# instead of before every single page request.
ROBOTS_CACHE_TTL_SECONDS = 3600
ROBOTS_FETCH_TIMEOUT_SECONDS = 5

# host -> (expires_at, RobotFileParser | None, fetch_allowed_on_error)
_robots_cache: dict[str, tuple[float, RobotFileParser | None, bool]] = {}
_cache_lock = threading.Lock()


def _load_robots(host_key: str, robots_url: str, user_agent: str) -> tuple[RobotFileParser | None, bool]:
    """Fetch and parse robots.txt once; cached by host for ROBOTS_CACHE_TTL_SECONDS.

    A missing robots.txt (404) means no published restrictions.  A denied or
    unavailable robots endpoint is NOT permission to crawl (fail closed).
    """
    now = time.monotonic()
    with _cache_lock:
        cached = _robots_cache.get(host_key)
        if cached and cached[0] > now:
            return cached[1], cached[2]

    parser: RobotFileParser | None = None
    allowed_on_error = False
    try:
        response = requests.get(
            robots_url,
            timeout=ROBOTS_FETCH_TIMEOUT_SECONDS,
            headers={"User-Agent": user_agent},
        )
        if response.status_code == 404:
            allowed_on_error = True
        elif response.status_code >= 400:
            allowed_on_error = False
        else:
            parser = RobotFileParser()
            parser.parse(response.text.splitlines())
    except Exception:
        allowed_on_error = False

    with _cache_lock:
        _robots_cache[host_key] = (now + ROBOTS_CACHE_TTL_SECONDS, parser, allowed_on_error)
    return parser, allowed_on_error


def can_fetch_url(url: str, user_agent: str) -> bool:
    parsed = urlparse(url)
    host_key = parsed.netloc.lower()
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser, allowed_on_error = _load_robots(host_key, robots_url, user_agent)
    if parser is None:
        return allowed_on_error
    return parser.can_fetch(user_agent, url)


def crawl_delay_for(url: str, user_agent: str) -> float:
    """Return the host's robots.txt Crawl-delay in seconds (0 when unspecified)."""
    parsed = urlparse(url)
    host_key = parsed.netloc.lower()
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser, _ = _load_robots(host_key, robots_url, user_agent)
    if parser is None:
        return 0.0
    try:
        delay = parser.crawl_delay(user_agent)
    except Exception:
        return 0.0
    if delay is None:
        return 0.0
    try:
        return max(0.0, float(delay))
    except (TypeError, ValueError):
        return 0.0


def clear_robots_cache() -> None:
    """Test hook: drop all cached robots.txt documents."""
    with _cache_lock:
        _robots_cache.clear()
