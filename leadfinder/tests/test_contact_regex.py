from leadfinder.services.crawl.contact_regex import extract_emails, extract_phones


def test_extracts_email_from_visible_contact_text():
    text = "For school visits and media contact, email hello@authorstudio.com."
    assert extract_emails(text) == ["hello@authorstudio.com"]


def test_ignores_script_like_emails():
    text = "const user = 'test@example.com'; function send(){ return 'admin@example.com'; }"
    assert extract_emails(text) == []


def test_extracts_phone_with_context():
    text = "For booking and school visit contact call +1 650-253-0000."
    assert extract_phones(text) == ["+1 650-253-0000"]


def test_rejects_no_context_phone():
    text = "Random number +1 650-253-0000 appears without explanation."
    assert extract_phones(text) == []


def test_rejects_blacklisted_email_domains():
    # Catalog and platform-level support/admin emails should be completely bypassed
    text = "Contact us at openlibrary@archive.org or support@goodreads.com for book help."
    assert extract_emails(text) == []


def test_rejects_isbn13_phones():
    # ISBN-13 sequences resembling phones should be suppressed
    text = "Call us for media bookings at 9781797227658."
    assert extract_phones(text) == []


def test_rejects_isbn10_with_catalog_context():
    # ISBN-10 values that resemble US phones should be suppressed in catalog context
    text = "ISBN-10: 1681241376. Please call contact desk."
    assert extract_phones(text) == []


def test_preserves_valid_phone_near_isbn_if_unrelated():
    # A true phone number in booking text should not be suppressed by an ISBN elsewhere on the page
    text = "For school visits and media contact, call +1 650-253-0000. Book ISBN is 1681241376."
    assert extract_phones(text) == ["+1 650-253-0000"]

