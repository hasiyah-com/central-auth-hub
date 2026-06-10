"""OIDC Discovery fetch + memory cache."""

from __future__ import annotations

import time

import httpx

from .config import Config
from .errors import HubError


class Discovery:
    """Fetch /.well-known/openid-configuration with TTL cache.

    Cache lives in instance — for cross-request cache, share instance.
    """

    def __init__(self, config: Config):
        self.config = config
        self._cached: dict | None = None
        self._cached_at: float = 0.0

    def get(self) -> dict:
        now = time.time()
        if self._cached and (now - self._cached_at) < self.config.jwks_cache_ttl:
            return self._cached

        url = f"{self.config.hub_url}/.well-known/openid-configuration"
        try:
            r = httpx.get(url, timeout=self.config.http_timeout)
            r.raise_for_status()
            doc = r.json()
        except Exception as e:
            raise HubError(f"Discovery fetch failed: {e}") from e

        if "issuer" not in doc or "jwks_uri" not in doc:
            raise HubError("Discovery missing required fields")
        self._cached = doc
        self._cached_at = now
        return doc

    async def get_async(self) -> dict:
        now = time.time()
        if self._cached and (now - self._cached_at) < self.config.jwks_cache_ttl:
            return self._cached
        url = f"{self.config.hub_url}/.well-known/openid-configuration"
        try:
            async with httpx.AsyncClient(timeout=self.config.http_timeout) as client:
                r = await client.get(url)
                r.raise_for_status()
                doc = r.json()
        except Exception as e:
            raise HubError(f"Discovery fetch failed: {e}") from e
        if "issuer" not in doc or "jwks_uri" not in doc:
            raise HubError("Discovery missing required fields")
        self._cached = doc
        self._cached_at = now
        return doc
