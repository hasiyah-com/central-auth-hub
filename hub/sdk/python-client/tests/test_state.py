"""State (CSRF) — RFC 6749 §10.12."""

import re

import pytest

from central_auth_hub.errors import StateError
from central_auth_hub.state import generate_state, verify_state


class TestState:
    def test_generate_32_hex(self):
        s = generate_state()
        assert len(s) == 32
        assert re.fullmatch(r"[0-9a-f]{32}", s)

    def test_match_passes(self):
        verify_state("abc123", "abc123")  # no exception

    def test_mismatch_raises(self):
        with pytest.raises(StateError, match="mismatch"):
            verify_state("expected", "attacker")

    def test_missing_expected_raises(self):
        with pytest.raises(StateError):
            verify_state("", "anything")

    def test_timing_safe(self):
        with pytest.raises(StateError):
            verify_state("abcd1234", "abcd1235")
