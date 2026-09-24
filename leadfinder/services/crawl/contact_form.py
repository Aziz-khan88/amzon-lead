"""Detect on-site contact forms on crawled author pages.

Many author sites expose no visible email at all — the only contact channel
is a ``<form>``.  The pipeline used to record nothing in that case.  This
module finds forms that look like contact channels (contact-ish action URL,
or email/message/comment fields) so the lead keeps an actionable contact
route even when no email or phone is published.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


CONTACT_ACTION_HINT_RE = re.compile(
    r"(contact|enquir|inquir|message|get-in-touch|reach|write-to|mail|form)",
    re.IGNORECASE,
)
CONTACT_FIELD_HINT_RE = re.compile(
    r"(email|e-mail|message|comment|enquir|inquir|subject|your-name|fullname)",
    re.IGNORECASE,
)
# Forms that are obviously NOT contact channels.
NON_CONTACT_ACTION_RE = re.compile(
    r"(search|login|signin|sign-in|cart|checkout|subscribe|newsletter|comment-post|wp-login|add-to-cart)",
    re.IGNORECASE,
)


def detect_contact_forms(html: str, page_url: str) -> list[dict]:
    """Return contact-form descriptors found in ``html``.

    Each item is ``{"url": absolute_form_action, "kind": str, "fields": [...]}``
    where ``kind`` is ``contact_form`` for an explicit contact form or
    ``generic_form`` for a message-like form.  Search/login/cart/newsletter
    forms are excluded.
    """

    if not html:
        return []
    forms: list[dict] = []
    seen: set[str] = set()
    soup = BeautifulSoup(html, "lxml")
    for form in soup.find_all("form"):
        action = str(form.get("action") or "").strip()
        absolute = urljoin(page_url, action) if action else page_url
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        field_names = " ".join(
            str(field.get("name") or field.get("id") or field.get("placeholder") or "")
            for field in form.find_all(["input", "textarea", "select"])
        )
        form_id_class = f"{form.get('id') or ''} {form.get('class') or ''}"
        if NON_CONTACT_ACTION_RE.search(absolute) or NON_CONTACT_ACTION_RE.search(form_id_class):
            continue
        action_hint = bool(CONTACT_ACTION_HINT_RE.search(absolute) or CONTACT_ACTION_HINT_RE.search(form_id_class))
        field_hint = bool(CONTACT_FIELD_HINT_RE.search(field_names))
        has_message_box = form.find("textarea") is not None
        if not (action_hint or (field_hint and has_message_box)):
            continue
        key = absolute.split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        forms.append(
            {
                "url": absolute,
                "kind": "contact_form" if action_hint else "generic_form",
                "fields": [name for name in field_names.split() if name][:10],
            }
        )
    return forms
