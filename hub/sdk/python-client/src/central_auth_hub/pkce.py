"""PKCE — RFC 7636 S256."""

from __future__ import annotations

import base64
import hashlib
import secrets


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def generate_verifier(length: int = 64) -> str:
    """Generate code_verifier (RFC 7636 §4.1) — 43..128 chars."""
    if length < 43 or length > 128:
        raise ValueError("verifier length must be 43..128")
    return _b64url(secrets.token_bytes(length))


def challenge_for(verifier: str) -> str:
    """code_challenge = BASE64URL(SHA256(verifier)) — RFC 7636 §4.2"""
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
