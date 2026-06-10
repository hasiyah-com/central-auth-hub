"""JWT verification — RFC 7519 + JWKS (RFC 7517) + auto key rotation."""

from __future__ import annotations

import time

import httpx
import jwt as pyjwt
from jwt.algorithms import RSAAlgorithm

from .config import Config
from .discovery import Discovery
from .errors import JwtError


class JwtVerifier:
    """Verify JWT signature + aud + iss + exp via JWKS.

    JWKS is cached (10 min default) — auto-refresh on unknown kid.
    """

    def __init__(self, config: Config, discovery: Discovery):
        self.config = config
        self.discovery = discovery
        self._jwks: dict | None = None
        self._jwks_at: float = 0.0

    def verify(self, token: str) -> dict:
        """Verify access_token → return claims dict."""
        disc = self.discovery.get()
        jwks_uri = disc["jwks_uri"]
        issuer = disc["issuer"]

        try:
            header = pyjwt.get_unverified_header(token)
        except Exception as e:
            raise JwtError(f"Bad JWT header: {e}") from e
        kid = header.get("kid")

        keys = self._get_keys(jwks_uri, refresh=False)
        if kid and kid not in keys:
            # try refresh — kid may be from key rotation
            keys = self._get_keys(jwks_uri, refresh=True)
        if kid and kid not in keys:
            raise JwtError(f"Unknown signing key kid={kid!r}")

        pub_key = keys.get(kid) if kid else next(iter(keys.values()), None)
        if pub_key is None:
            raise JwtError("No public key available")

        try:
            claims = pyjwt.decode(
                token,
                pub_key,
                algorithms=["RS256"],
                audience=self.config.client_id,
                issuer=issuer,
                options={
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_exp": True,
                    "verify_signature": True,
                },
                leeway=30,
            )
        except Exception as e:
            raise JwtError(f"JWT verify failed: {e}") from e
        return claims

    def _get_keys(self, jwks_uri: str, refresh: bool) -> dict:
        """Return {kid: public_key} dict."""
        now = time.time()
        if (
            not refresh
            and self._jwks is not None
            and (now - self._jwks_at) < self.config.jwks_cache_ttl
        ):
            return self._jwks

        try:
            r = httpx.get(jwks_uri, timeout=self.config.http_timeout)
            r.raise_for_status()
            jwks = r.json()
        except Exception as e:
            raise JwtError(f"JWKS fetch failed: {e}") from e
        if "keys" not in jwks:
            raise JwtError("JWKS missing 'keys'")

        out = {}
        for jwk in jwks["keys"]:
            try:
                out[jwk["kid"]] = RSAAlgorithm.from_jwk(jwk)
            except Exception:
                continue
        self._jwks = out
        self._jwks_at = now
        return out
