"""Optional headless-browser fallback for JavaScript-rendered author sites.

Modern site builders (Wix, Squarespace, React portfolios) return a nearly
empty HTML shell to plain ``requests`` fetches, so the crawler sees no text
and extracts no contacts.  When ``APP_JS_RENDER_ENABLED=1`` and Playwright is
installed, pages whose visible text is thinner than
``APP_JS_RENDER_MIN_TEXT_CHARS`` are re-rendered headlessly once.

Everything degrades gracefully: if Playwright is not installed, the setting
is off, or rendering fails, the original fetched page is used unchanged.
"""

from __future__ import annotations

import logging

from django.conf import settings

from leadfinder.services.crawl.extract_text import extract_visible_text
from leadfinder.utils.url_safety import is_safe_public_url


logger = logging.getLogger(__name__)

_BROWSER = None
_PLAYWRIGHT = None
_IMPORT_FAILED = False


def js_render_available() -> bool:
    """True when the feature is enabled and Playwright + Chromium are usable."""

    global _IMPORT_FAILED
    if not getattr(settings, "APP_JS_RENDER_ENABLED", False):
        return False
    if _IMPORT_FAILED:
        return False
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:
        _IMPORT_FAILED = True
        return False
    return True


def _browser():
    """Lazily launch one shared headless Chromium for the process."""

    global _BROWSER, _PLAYWRIGHT
    if _BROWSER is not None:
        return _BROWSER
    from playwright.sync_api import sync_playwright

    _PLAYWRIGHT = sync_playwright().start()
    _BROWSER = _PLAYWRIGHT.chromium.launch(headless=True)
    return _BROWSER


def render_page_html(url: str, timeout_ms: int = 20_000) -> str | None:
    """Render ``url`` in headless Chromium and return the settled HTML."""

    if not is_safe_public_url(url):
        return None
    try:
        browser = _browser()
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) BookTrailerLeadFinder/1.0",
            viewport={"width": 1366, "height": 900},
        )
        try:
            page = context.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            # Give client-side rendering a short, bounded moment to settle.
            page.wait_for_timeout(1500)
            return page.content()
        finally:
            context.close()
    except Exception as exc:  # noqa: BLE001 - any browser failure falls back to raw HTML
        logger.info("JS render failed for %s: %s", url, exc)
        return None


def rerender_if_thin(fetched, min_text_chars: int | None = None):
    """Return a replacement page via JS rendering when the fetch looks empty.

    ``fetched`` is a ``safe_fetch.FetchedPage`` (or None).  When rendering is
    unavailable, disabled, or fails, the original object is returned so callers
    never need to branch.
    """

    if fetched is None or not fetched.html:
        return fetched
    if not js_render_available():
        return fetched
    threshold = min_text_chars
    if threshold is None:
        threshold = int(getattr(settings, "APP_JS_RENDER_MIN_TEXT_CHARS", 200))
    if len(extract_visible_text(fetched.html).strip()) >= threshold:
        return fetched
    rendered = render_page_html(fetched.url)
    if not rendered or len(rendered) <= len(fetched.html):
        return fetched
    from leadfinder.services.crawl.safe_fetch import FetchedPage

    return FetchedPage(
        url=fetched.url,
        status_code=fetched.status_code,
        html=rendered,
        content_type=fetched.content_type or "text/html",
    )
