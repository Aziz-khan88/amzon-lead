from __future__ import annotations

from types import SimpleNamespace

from leadfinder.services.crawl.robots import can_fetch_url
from leadfinder.services.crawl.safe_fetch import safe_fetch


def test_robots_failure_is_not_treated_as_crawl_permission(monkeypatch):
    monkeypatch.setattr(
        "leadfinder.services.crawl.robots.requests.get",
        lambda *args, **kwargs: SimpleNamespace(status_code=503, text=""),
    )

    assert can_fetch_url("https://author.example/contact", "test-agent") is False


def test_safe_fetch_rechecks_redirect_destination_before_requesting_it(monkeypatch):
    class RedirectResponse:
        is_redirect = True
        is_permanent_redirect = False
        headers = {"location": "https://www.amazon.com/dp/B0TEST0001"}
        status_code = 302

        def close(self):
            return None

    requested_urls = []

    def fake_get(url, **kwargs):
        requested_urls.append(url)
        return RedirectResponse()

    monkeypatch.setattr("leadfinder.services.crawl.safe_fetch.can_fetch_url", lambda *args: True)
    monkeypatch.setattr("leadfinder.services.crawl.safe_fetch.time.sleep", lambda *args: None)
    monkeypatch.setattr("leadfinder.services.crawl.safe_fetch.requests.get", fake_get)

    assert safe_fetch("https://author.example/about") is None
    assert requested_urls == ["https://author.example/about"]
