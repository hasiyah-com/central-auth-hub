"""Webhook receiver — HMAC verify + replay."""

import hashlib
import hmac
import json
import time

import pytest

from central_auth_hub.errors import HubError
from central_auth_hub.webhook import verify_webhook


class TestWebhook:
    def _sig(self, body: bytes, key: str) -> str:
        return hmac.new(key.encode(), body, hashlib.sha256).hexdigest()

    def test_valid_signature_accepts(self):
        body = json.dumps({"event": "access_revoked", "hub_user_id": "u1"}).encode()
        ts = str(int(time.time()))
        key = "k"
        sig = self._sig(body, key)
        payload = verify_webhook(
            key,
            body,
            {"X-Hub-Signature-256": sig, "X-Hub-Timestamp": ts},
        )
        assert payload["event"] == "access_revoked"
        assert payload["hub_user_id"] == "u1"

    def test_bad_signature_rejects(self):
        body = b'{"x":1}'
        ts = str(int(time.time()))
        with pytest.raises(HubError, match="signature mismatch"):
            verify_webhook(
                "k",
                body,
                {"X-Hub-Signature-256": "a" * 64, "X-Hub-Timestamp": ts},
            )

    def test_expired_timestamp_rejects(self):
        body = b'{"x":1}'
        ts = str(int(time.time()) - 600)  # 10 min old
        sig = self._sig(body, "k")
        with pytest.raises(HubError, match="out of tolerance"):
            verify_webhook(
                "k",
                body,
                {"X-Hub-Signature-256": sig, "X-Hub-Timestamp": ts},
            )

    def test_missing_headers_rejects(self):
        with pytest.raises(HubError, match="Missing"):
            verify_webhook("k", b"{}", {})

    def test_bad_timestamp_format(self):
        body = b'{"x":1}'
        with pytest.raises(HubError, match="timestamp format"):
            verify_webhook(
                "k",
                body,
                {
                    "X-Hub-Signature-256": "x",
                    "X-Hub-Timestamp": "not-a-number",
                },
            )

    def test_case_insensitive_headers(self):
        body = b'{"y":2}'
        ts = str(int(time.time()))
        sig = self._sig(body, "k")
        payload = verify_webhook(
            "k",
            body,
            {"x-hub-signature-256": sig, "x-hub-timestamp": ts},
        )
        assert payload["y"] == 2
