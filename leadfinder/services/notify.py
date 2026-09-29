"""Outbound webhook notifications for pipeline events.

Set ``APP_WEBHOOK_URL`` to a Slack/Discord/generic HTTPS endpoint and the
pipeline posts a small JSON payload when a run finishes or a hot lead is
found.  Everything is fire-and-forget: no URL configured, unsafe URL, or any
network error is logged and swallowed so notifications can never break a run.
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from leadfinder.utils.url_safety import is_safe_public_url


logger = logging.getLogger(__name__)


def notify_webhook(event: str, text: str, payload: dict | None = None) -> bool:
    """POST a Slack-compatible message to the configured webhook. Never raises."""

    url = (getattr(settings, "APP_WEBHOOK_URL", "") or "").strip()
    if not url or not is_safe_public_url(url):
        return False
    timeout = int(getattr(settings, "APP_REQUEST_TIMEOUT_SECONDS", 15))
    body = {"text": text, "event": event}
    if payload:
        body.update(payload)
    try:
        response = requests.post(url, json=body, timeout=timeout)
        if response.status_code >= 400:
            logger.info("Webhook POST %s returned %s", event, response.status_code)
            return False
        return True
    except requests.RequestException as exc:
        logger.info("Webhook POST %s failed: %s", event, exc)
        return False


def notify_run_completed(run) -> bool:
    books_total = run.books.count()
    from leadfinder.models import Lead

    leads = Lead.objects.filter(book__research_run=run)
    verified = leads.filter(verification_status="verified").count()
    hot = leads.filter(lead_tier="hot").count()
    return notify_webhook(
        "run_completed",
        f"Lead research run completed: '{run.keyword or run.source_provider}' — "
        f"{books_total} books, {leads.count()} leads, {verified} verified, {hot} hot.",
        {"run_id": str(run.id), "books": books_total, "leads": leads.count(), "verified": verified, "hot": hot},
    )


def notify_hot_lead(lead) -> bool:
    threshold = int(getattr(settings, "APP_HOT_LEAD_NOTIFY_SCORE", 90))
    if lead.lead_score < threshold or lead.lead_tier != "hot":
        return False
    return notify_webhook(
        "hot_lead",
        f"Hot lead found: '{lead.book.title}' by {lead.book.author_name or 'Unknown'} "
        f"(score {lead.lead_score}, email: {lead.public_email or lead.representation_email or lead.publicist_email or 'n/a'}).",
        {
            "lead_id": str(lead.id),
            "score": lead.lead_score,
            "title": lead.book.title,
            "author": lead.book.author_name,
        },
    )
