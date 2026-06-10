"""State (CSRF token) — RFC 6749 §10.12."""

from __future__ import annotations

import hmac
import secrets

from .errors import StateError


def generate_state() -> str:
    """32-char hex random state."""
    return secrets.token_hex(16)


def verify_state(expected: str, provided: str) -> None:
    """Constant-time compare — raise StateError on mismatch."""
    if not expected:
        raise StateError("No state to verify (session expired?)")
    if not hmac.compare_digest(expected, provided):
        raise StateError("State mismatch — possible CSRF attack")
