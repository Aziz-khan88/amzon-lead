from __future__ import annotations

from types import SimpleNamespace

from leadfinder.services.crawl import robots
from leadfinder.services.crawl.robots import can_fetch_url, crawl_delay_for
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
    monkeypatch.setattr("leadfinder.services.crawl.safe_fetch.is_safe_public_url", lambda url: True)
    monkeypatch.setattr("leadfinder.services.crawl.safe_fetch.time.sleep", lambda *args: None)
    monkeypatch.setattr("leadfinder.services.crawl.safe_fetch.requests.get", fake_get)

    assert safe_fetch("https://author.example/about") is None
    assert requested_urls == ["https://author.example/about"]


def test_robots_txt_is_fetched_once_per_host(monkeypatch):
    robots.clear_robots_cache()
    requested = []

    def fake_get(url, **kwargs):
        requested.append(url)
        return SimpleNamespace(status_code=404, text="")

    monkeypatch.setattr("leadfinder.services.crawl.robots.requests.get", fake_get)

    assert can_fetch_url("https://cached.example/about", "test-agent") is True
    assert can_fetch_url("https://cached.example/contact", "test-agent") is True
    assert requested == ["https://cached.example/robots.txt"]
    robots.clear_robots_cache()


def test_crawl_delay_is_read_from_robots_txt(monkeypatch):
    robots.clear_robots_cache()
    body = "User-agent: *\nCrawl-delay: 5\n"

    monkeypatch.setattr(
        "leadfinder.services.crawl.robots.requests.get",
        lambda *args, **kwargs: SimpleNamespace(status_code=200, text=body),
    )

    assert crawl_delay_for("https://slow.example/contact", "test-agent") == 5.0
    assert can_fetch_url("https://slow.example/contact", "test-agent") is True
    robots.clear_robots_cache()
