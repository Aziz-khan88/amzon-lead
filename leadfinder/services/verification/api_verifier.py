"""Optional third-party email-deliverability APIs.

Direct SMTP RCPT-TO probing (port 25) is blocked on most residential and
cloud networks, so ``mx_validator.check_deliverability`` usually returns
``unknown``.  When a provider API key is configured, this module asks a
hosted verification service instead and maps its verdict onto the same
``deliverable / undeliverable / catch_all / unknown`` vocabulary the verifier
already understands.

Priority: ``APP_EMAIL_VERIFY_PROVIDER`` picks the provider
(``hunter`` | ``zerobounce`` | ``neverbounce``); without a matching API key
the function returns None and the pipeline falls back to SMTP/MX behavior.
All calls are bounded by ``APP_REQUEST_TIMEOUT_SECONDS`` and never raise.
"""

from __future__ import annotations

import logging
import os

import requests
from django.conf import settings


logger = logging.getLogger(__name__)


def _hunter(email: str, api_key: str, timeout: int) -> dict | None:
    response = requests.get(
        "https://api.hunter.io/v2/email-verifier",
        params={"email": email, "api_key": api_key},
        timeout=timeout,
    )
    if response.status_code != 200:
        return None
    data = (response.json() or {}).get("data") or {}
    status = str(data.get("status") or "").lower()
    if data.get("accept_all"):
        mapped = "catch_all"
    elif status == "valid":
        mapped = "deliverable"
    elif status == "invalid":
        mapped = "undeliverable"
    else:
        mapped = "unknown"
    return {"status": mapped, "message": f"hunter:{status or 'unknown'}", "provider": "hunter"}


def _zerobounce(email: str, api_key: str, timeout: int) -> dict | None:
    response = requests.get(
        "https://api.zerobounce.net/v2/validate",
        params={"email": email, "api_key": api_key},
        timeout=timeout,
    )
    if response.status_code != 200:
        return None
    data = response.json() or {}
    status = str(data.get("status") or "").lower()
    sub_status = str(data.get("sub_status") or "").lower()
    if status == "valid":
        mapped = "deliverable"
    elif status == "catch-all":
        mapped = "catch_all"
    elif status in {"invalid", "abuse", "spamtrap"}:
        mapped = "undeliverable"
    else:
        mapped = "unknown"
    return {"status": mapped, "message": f"zerobounce:{status}:{sub_status}".rstrip(":"), "provider": "zerobounce"}


def _neverbounce(email: str, api_key: str, timeout: int) -> dict | None:
    response = requests.get(
        "https://api.neverbounce.com/v4/single/check",
        params={"email": email, "key": api_key},
        timeout=timeout,
    )
    if response.status_code != 200:
        return None
    data = response.json() or {}
    result = str(data.get("result") or "").lower()
    mapping = {
        "valid": "deliverable",
        "invalid": "undeliverable",
        "catchall": "catch_all",
        "disposable": "undeliverable",
    }
    return {"status": mapping.get(result, "unknown"), "message": f"neverbounce:{result or 'unknown'}", "provider": "neverbounce"}


_PROVIDERS = {
    "hunter": ("HUNTER_API_KEY", _hunter),
    "zerobounce": ("ZEROBOUNCE_API_KEY", _zerobounce),
    "neverbounce": ("NEVERBOUNCE_API_KEY", _neverbounce),
}


def api_verify_email(email: str) -> dict | None:
    """Verify ``email`` via the configured API provider, or None if unavailable.

    Never raises — network errors, missing keys, and bad responses all return
    None so the caller can fall back to its default behavior.
    """

    provider = (getattr(settings, "APP_EMAIL_VERIFY_PROVIDER", "") or "").strip().lower()
    if provider not in _PROVIDERS:
        return None
    env_key, handler = _PROVIDERS[provider]
    api_key = os.getenv(env_key, "").strip()
    if not api_key:
        return None
    timeout = int(getattr(settings, "APP_REQUEST_TIMEOUT_SECONDS", 15))
    try:
        return handler(email, api_key, timeout)
    except requests.RequestException as exc:
        logger.info("Email verification API %s failed for %s: %s", provider, email, exc)
        return None
