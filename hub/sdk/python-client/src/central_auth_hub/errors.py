"""Typed exceptions for SDK."""


class HubError(Exception):
    """Base for all SDK errors."""


class StateError(HubError):
    """CSRF state mismatch — RFC 6749 §10.12."""


class TokenError(HubError):
    """Token exchange failed at /oauth/token."""


class JwtError(HubError):
    """JWT verification failed (signature/aud/iss/exp)."""
