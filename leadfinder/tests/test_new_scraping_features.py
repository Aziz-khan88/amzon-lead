"""Tests for the 2026-08-18 lead-scraping feature additions:

- deobfuscate.py        — hidden/obfuscated contact recovery from raw HTML
- contact_form.py       — on-site contact-form detection
- lead_validator        — phone line-type + fake/premium screening
- proxies.py            — deterministic per-host proxy rotation
- api_verifier.py       — hosted email-verification API mapping
- site_providers.py     — Kickstarter/Goodreads/SCBWI/Amazon-new-releases discovery
- shared_contacts.py    — cross-lead shared contact-channel detection
- notify.py             — webhook notifications
- profile_harvester     — follower-count parsing
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.utils import timezone

from leadfinder.models import AuthorProfile, Book, ContactCandidate, Lead, ResearchRun
from leadfinder.services.crawl.contact_form import detect_contact_forms
from leadfinder.services.crawl.deobfuscate import (
    decode_cloudflare_hex,
    extract_hidden_contacts,
    obfuscated_emails_from_text,
)
from leadfinder.services.crawl.proxies import proxies_for_url
from leadfinder.services.discovery.site_providers import (
    KICKSTARTER_PROVIDER,
    AMAZON_NEW_RELEASES_PROVIDER,
    SiteDiscoveryProvider,
)
from leadfinder.services.pipeline.lead_validator import phone_number_details
from leadfinder.services.pipeline.shared_contacts import count_leads_sharing_contact
from leadfinder.services.social.profile_harvester import _parse_follower_count
from leadfinder.utils.normalize import normalized_book_key


def _cloudflare_payload(email: str, key: int = 0x5A) -> str:
    return f"{key:02x}" + "".join(f"{ord(character) ^ key:02x}" for character in email)


# ---------------------------------------------------------------- deobfuscate


def test_extract_hidden_contacts_finds_mailto_cfemail_and_jsonld():
    html = f"""
        <html><head>
        <script type="application/ld+json">{{"email": "press@lunabooks.com"}}</script>
        </head><body>
            <a href="mailto:studio%40lunabooks.com?subject=Hello">Email</a>
            <a href="tel:+1-303-555-0177">Call the studio</a>
            <span data-cfemail="{_cloudflare_payload('agent@lunabooks.com')}">[protected]</span>
        </body></html>
    """

    emails, phones = extract_hidden_contacts(html)

    assert "studio@lunabooks.com" in emails
    assert "agent@lunabooks.com" in emails
    assert "press@lunabooks.com" in emails
    assert "+13035550177" in phones


def test_obfuscated_at_dot_prose_is_recovered_but_stopwords_are_not():
    emails = obfuscated_emails_from_text(
        "For bookings write luna.ray [at] lunabooks [dot] com. "
        "If unsure, contact me at the studio instead."
    )

    assert "luna.ray@lunabooks.com" in emails
    assert not any(email.startswith("me@") for email in emails)


def test_decode_cloudflare_hex_rejects_garbage():
    assert decode_cloudflare_hex("") == ""
    assert decode_cloudflare_hex("xyz") == ""
    assert decode_cloudflare_hex("123") == ""


def test_extract_hidden_contacts_handles_empty_input():
    assert extract_hidden_contacts("") == ([], [])


# --------------------------------------------------------------- contact form


def test_detect_contact_forms_finds_contact_form_and_skips_search_form():
    html = """
        <html><body>
            <form action="/search"><input name="q"></form>
            <form action="/newsletter-signup"><input name="email"></form>
            <form action="/contact-me" method="post">
                <input name="name"><input name="email"><textarea name="message"></textarea>
            </form>
        </body></html>
    """

    forms = detect_contact_forms(html, "https://author.example/about")

    assert [form["url"] for form in forms] == ["https://author.example/contact-me"]
    assert forms[0]["kind"] == "contact_form"


def test_detect_contact_forms_message_box_with_contact_fields_counts():
    html = """
        <form action="/submit" method="post">
            <input name="your-email"><textarea name="your-message"></textarea>
        </form>
    """

    forms = detect_contact_forms(html, "https://author.example/")

    assert len(forms) == 1
    assert forms[0]["kind"] == "generic_form"


# -------------------------------------------------------------------- phones


def test_phone_details_classifies_fake_and_premium_numbers():
    fake = phone_number_details("(212) 555-0142")
    premium = phone_number_details("1-900-555-0100")
    normal = phone_number_details("(415) 222-3344")

    assert fake["is_fake"] and not fake["valid"]
    assert premium["is_premium"] and not premium["valid"]
    assert normal["valid"] and normal["e164"] == "+14152223344"
    assert normal["line_type"] in {"landline", "mobile", "voip"}
    assert phone_number_details("")["valid"] is False
    assert phone_number_details("not-a-phone")["valid"] is False


# -------------------------------------------------------------------- proxies


def test_proxy_rotation_is_deterministic_per_host(settings):
    settings.APP_PROXY_LIST = ""
    assert proxies_for_url("https://author.example/page") is None

    settings.APP_PROXY_LIST = "http://p1:8000, http://p2:8000"
    first = proxies_for_url("https://author.example/page")
    second = proxies_for_url("https://author.example/other")
    assert first == second
    assert first["http"] in {"http://p1:8000", "http://p2:8000"}


# --------------------------------------------------------------- api verifier


def test_api_verifier_returns_none_without_configuration(settings, monkeypatch):
    settings.APP_EMAIL_VERIFY_PROVIDER = ""
    from leadfinder.services.verification.api_verifier import api_verify_email

    assert api_verify_email("someone@example.com") is None

    settings.APP_EMAIL_VERIFY_PROVIDER = "hunter"
    monkeypatch.delenv("HUNTER_API_KEY", raising=False)
    assert api_verify_email("someone@example.com") is None


def test_api_verifier_maps_hunter_response(settings, monkeypatch):
    settings.APP_EMAIL_VERIFY_PROVIDER = "hunter"
    monkeypatch.setenv("HUNTER_API_KEY", "test-key")

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"data": {"status": "valid", "accept_all": False}}

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: FakeResponse())

    from leadfinder.services.verification.api_verifier import api_verify_email

    result = api_verify_email("author@example.com")
    assert result["status"] == "deliverable"
    assert result["provider"] == "hunter"


# -------------------------------------------------------------- site providers


class _FakeSearchProvider:
    provider_name = "fake"

    def __init__(self, results):
        self._results = results

    def search(self, query, max_results=8):
        return self._results


def _result(title, url, snippet=""):
    return SimpleNamespace(title=title, url=url, snippet=snippet, rank=1, provider="fake")


def test_kickstarter_discovery_parses_title_and_creator():
    provider = _FakeSearchProvider(
        [
            _result("The Sleepy Dragon: A Picture Book by Dana Cole", "https://www.kickstarter.com/projects/danacole/the-sleepy-dragon"),
            _result("Unrelated result", "https://www.example.com/nope"),
        ]
    )

    candidates, errors = KICKSTARTER_PROVIDER.discover("picture book", max_books=10, search_provider=provider)

    assert errors == []
    assert len(candidates) == 1
    assert candidates[0]["title"] == "The Sleepy Dragon: A Picture Book"
    assert candidates[0]["author_name"] == "Dana Cole"
    assert candidates[0]["source_provider"] == "kickstarter"
    assert candidates[0]["amazon_source_url"].startswith("https://www.kickstarter.com/")


def test_amazon_new_releases_requires_asin_and_dedupes():
    provider = _FakeSearchProvider(
        [
            _result("Moon Cat by L. Ray (Hardcover)", "https://www.amazon.com/dp/B0ABCDE123"),
            _result("Moon Cat by L. Ray (Hardcover)", "https://www.amazon.com/dp/B0ABCDE123?tag=x"),
            _result("Amazon help page", "https://www.amazon.com/gp/help"),
        ]
    )

    candidates, _ = AMAZON_NEW_RELEASES_PROVIDER.discover("", max_books=10, search_provider=provider)

    assert len(candidates) == 1
    assert candidates[0]["asin"] == "B0ABCDE123"
    assert candidates[0]["amazon_book_url"]


def test_site_provider_records_errors_without_raising():
    class FailingProvider:
        provider_name = "fake"

        def search(self, query, max_results=8):
            raise RuntimeError("boom")

    candidates, errors = KICKSTARTER_PROVIDER.discover("x", max_books=5, search_provider=FailingProvider())

    assert candidates == []
    assert errors


# ------------------------------------------------------------- shared contacts


@pytest.fixture
def lead_factory(db):
    def make(title: str, email: str):
        run = ResearchRun.objects.create(keyword="children picture book", source_provider="csv")
        book = Book.objects.create(
            research_run=run,
            title=title,
            author_name="Test Author",
            normalized_key=normalized_book_key(title, "Test Author", ""),
            source_provider="csv",
        )
        profile = AuthorProfile.objects.create(
            author_name="Test Author", normalized_author_key="test-author"
        )
        lead = Lead.objects.create(book=book, author_profile=profile, public_email=email)
        if email:
            ContactCandidate.objects.create(
                lead=lead, channel="email", raw_value=email, normalized_value=email
            )
        return lead

    return make


@pytest.mark.django_db
def test_shared_contact_count_excludes_current_lead(lead_factory):
    first = lead_factory("Book One", "agency@bigagency.com")
    lead_factory("Book Two", "agency@bigagency.com")
    lead_factory("Book Three", "agency@bigagency.com")

    assert count_leads_sharing_contact("email", "agency@bigagency.com", exclude_lead_id=first.id) == 2
    assert count_leads_sharing_contact("email", "agency@bigagency.com") == 3
    assert count_leads_sharing_contact("email", "") == 0


# ---------------------------------------------------------------- stale verify


@pytest.mark.django_db
def test_reverify_stale_contacts_flags_old_leads(lead_factory, monkeypatch, capsys):
    lead = lead_factory("Old Book", "author@example.com")
    candidate = ContactCandidate.objects.get(lead=lead)
    stale_time = timezone.now() - timedelta(days=120)
    ContactCandidate.objects.filter(id=candidate.id).update(last_checked_at=stale_time)
    Lead.objects.filter(id=lead.id).update(verification_status="verified")

    monkeypatch.setattr(
        "leadfinder.services.verification.verify_lead_contacts",
        lambda lead, **kwargs: lead,
    )
    # Patch the symbol imported inside the command module as well.
    import leadfinder.management.commands.reverify_stale_contacts as command_module

    monkeypatch.setattr(command_module, "verify_lead_contacts", lambda lead, **kwargs: lead)

    call_command("reverify_stale_contacts", "--days", "90", "--no-network")

    lead.refresh_from_db()
    assert lead.contacts_stale is False  # re-verified leads are unflagged
    assert "1 stale leads processed" in capsys.readouterr().out


# ------------------------------------------------------------- follower counts


def test_parse_follower_count_formats():
    assert _parse_follower_count("1,234 Followers") == 1234
    assert _parse_follower_count("3.2K followers and counting") == 3200
    assert _parse_follower_count("1.4M subscribers") == 1_400_000
    assert _parse_follower_count("no audience info here") is None


# -------------------------------------------------------------------- notify


def test_notify_webhook_noop_without_url(settings):
    settings.APP_WEBHOOK_URL = ""
    from leadfinder.services.notify import notify_webhook

    assert notify_webhook("test", "hello") is False


def test_notify_webhook_posts_payload(settings, monkeypatch):
    settings.APP_WEBHOOK_URL = "https://hooks.example.com/services/abc"
    monkeypatch.setattr("leadfinder.services.notify.is_safe_public_url", lambda url: True)
    posted = {}

    class FakeResponse:
        status_code = 200

    def fake_post(url, json, timeout):
        posted["url"] = url
        posted["json"] = json
        return FakeResponse()

    monkeypatch.setattr("requests.post", fake_post)

    from leadfinder.services.notify import notify_webhook

    assert notify_webhook("hot_lead", "Hot lead!", {"score": 95}) is True
    assert posted["json"]["event"] == "hot_lead"
    assert posted["json"]["score"] == 95
