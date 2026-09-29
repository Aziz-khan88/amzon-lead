from __future__ import annotations

from leadfinder.services.crawl.social_contact_crawler import (
    PublicHtmlPage,
    crawl_and_extract_social_contacts,
    decode_cloudflare_hex,
    extract_social_contacts,
)


def _cloudflare_payload(email: str, key: int = 0x12) -> str:
    return f"{key:02x}" + "".join(f"{ord(character) ^ key:02x}" for character in email)


def test_extracts_standard_obfuscated_mailto_and_cloudflare_email_addresses():
    cloudflare_email = "hello@averymoonbooks.com"
    html = f"""
        <html><body>
            <p>For school visits, write avery [at] averymoonbooks [dot] com.</p>
            <a href="mailto:booking%40averymoonbooks.com?subject=School%20visit">Email us</a>
            <a data-cfemail="{_cloudflare_payload(cloudflare_email)}">protected</a>
        </body></html>
    """

    emails, phones = extract_social_contacts(html)

    assert emails == [
        "booking@averymoonbooks.com",
        "hello@averymoonbooks.com",
        "avery@averymoonbooks.com",
    ]
    assert phones == []


def test_extracts_explicit_public_telephone_links_without_book_metadata_false_positives():
    emails, phones = extract_social_contacts(
        '<a href="tel:+1-202-555-0123">Call for bookings</a><p>ISBN: 9781797227658</p>'
    )

    assert emails == []
    assert phones == ["+12025550123"]


def test_cloudflare_decoder_rejects_malformed_payloads():
    assert decode_cloudflare_hex("") == ""
    assert decode_cloudflare_hex("zz") == ""
    assert decode_cloudflare_hex("123") == ""


def test_crawl_returns_deduplicated_contacts_and_source_pages(monkeypatch):
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return PublicHtmlPage(
            url=url,
            title="Avery Moon Books",
            text="Avery Moon writes The Moon Rabbit.",
            links=[],
            html='<a href="mailto:avery@averymoonbooks.com">Contact</a>',
        )

    monkeypatch.setattr("leadfinder.services.crawl.social_contact_crawler.is_safe_public_url", lambda url: True)
    monkeypatch.setattr("leadfinder.services.crawl.social_contact_crawler.fetch_public_html", fake_fetch)

    result = crawl_and_extract_social_contacts(
        ["https://linktr.ee/averymoon", "https://linktr.ee/averymoon"]
    )

    assert calls == ["https://linktr.ee/averymoon"]
    assert result == {
        "emails": ["avery@averymoonbooks.com"],
        "phones": [],
        "pages": ["https://linktr.ee/averymoon"],
    }
