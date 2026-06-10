"""PKCE — RFC 7636 conformance + edge cases."""

import re

import pytest

from central_auth_hub.pkce import challenge_for, generate_verifier


class TestPkce:
    def test_verifier_length_in_range(self):
        v = generate_verifier(64)
        assert 43 <= len(v) <= 128

    def test_verifier_uses_base64url(self):
        v = generate_verifier(64)
        assert re.fullmatch(r"[A-Za-z0-9_-]+", v)

    def test_two_verifiers_differ(self):
        assert generate_verifier(64) != generate_verifier(64)

    def test_rejects_too_short(self):
        with pytest.raises(ValueError):
            generate_verifier(32)

    def test_rejects_too_long(self):
        with pytest.raises(ValueError):
            generate_verifier(200)

    def test_challenge_matches_rfc7636_vector(self):
        """RFC 7636 §4.2 — Appendix B test vector."""
        verifier = (
            "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  # pragma: allowlist secret
        )
        challenge = (
            "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"  # pragma: allowlist secret
        )
        assert challenge_for(verifier) == challenge

    def test_challenge_deterministic(self):
        assert challenge_for("abc123") == challenge_for("abc123")
