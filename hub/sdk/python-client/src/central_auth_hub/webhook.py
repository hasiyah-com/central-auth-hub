"""Webhook receiver — HMAC-SHA256 + replay protection."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

from .errors import HubError


def verify_webhook(
    shared_key: str,
    raw_body: bytes,
    headers: dict,
    max_age_sec: int = 300,
) -> dict:
    """Verify HMAC signature + timestamp → return parsed payload.

    Headers expected (case-insensitive):
      X-Hub-Signature-256: hex(HMAC-SHA256(shared_key, raw_body))
      X-Hub-Timestamp:     epoch seconds

    Raises HubError on any failure.
    """
    # normalize headers (lower-case)
    h = {k.lower(): v for k, v in headers.items()}
    sig = h.get("x-hub-signature-256", "")
    ts = h.get("x-hub-timestamp", "")
    if not sig or not ts:
        raise HubError("Missing X-Hub-Signature-256 or X-Hub-Timestamp")

    # replay protection
    try:
        ts_int = int(ts)
    except ValueError:
        raise HubError("Bad timestamp format") from None
    if abs(int(time.time()) - ts_int) > max_age_sec:
        raise HubError(f"Webhook timestamp out of tolerance ({max_age_sec}s)")

    # HMAC verify (timing-safe)
    expected = hmac.new(
        shared_key.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HubError("Webhook signature mismatch")

    try:
        return json.loads(raw_body.decode("utf-8"))
    except Exception as e:
        raise HubError(f"Body not valid JSON: {e}") from e
