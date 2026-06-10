"""HubClient — main facade.

API:
    hub = HubClient(hub_url=..., client_id=..., client_secret=..., redirect_uri=...)
    auth_url, state, verifier = hub.build_authorize_url(return_to="/dashboard")
    # ... user redirects, returns with code+state ...
    claims = hub.handle_callback(code, received_state, expected_state, verifier)
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from .config import Config
from .discovery import Discovery
from .jwt_verifier import JwtVerifier
from .pkce import challenge_for, generate_verifier
from .state import generate_state, verify_state
from .token_exchange import exchange_code, exchange_code_async


class HubClient:
    """Sync + async sibling APIs.

    Note: session storage of state/verifier is left to the caller (framework-agnostic).
    Helper builders for FastAPI/Flask are in examples/.
    """

    def __init__(
        self,
        *,
        hub_url: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scope: list[str] | None = None,
        jwks_cache_ttl: int = 600,
        http_timeout: float = 10.0,
    ):
        self.config = Config(
            hub_url=hub_url,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=list(scope) if scope else ["openid", "profile", "email"],
            jwks_cache_ttl=jwks_cache_ttl,
            http_timeout=http_timeout,
        )
        self.discovery = Discovery(self.config)
        self.jwt_verifier = JwtVerifier(self.config, self.discovery)

    # ── Sync ──

    def build_authorize_url(self, return_to: str | None = None) -> tuple[str, str, str]:
        """Return (auth_url, state, verifier) — caller stores state+verifier in session."""
        disc = self.discovery.get()
        state = generate_state()
        verifier = generate_verifier()
        challenge = challenge_for(verifier)
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.config.scope),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        url = disc["authorization_endpoint"] + "?" + urlencode(params)
        return url, state, verifier

    def handle_callback(
        self,
        code: str,
        received_state: str,
        expected_state: str,
        verifier: str,
    ) -> dict[str, Any]:
        """Verify state, exchange code, verify JWT → return claims."""
        verify_state(expected_state, received_state)
        disc = self.discovery.get()
        token_resp = exchange_code(self.config, disc["token_endpoint"], code, verifier)
        claims = self.jwt_verifier.verify(token_resp["access_token"])
        claims["_access_token"] = token_resp["access_token"]
        return claims

    # ── Async ──

    async def build_authorize_url_async(
        self, return_to: str | None = None
    ) -> tuple[str, str, str]:
        disc = await self.discovery.get_async()
        state = generate_state()
        verifier = generate_verifier()
        challenge = challenge_for(verifier)
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.config.scope),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        url = disc["authorization_endpoint"] + "?" + urlencode(params)
        return url, state, verifier

    async def handle_callback_async(
        self,
        code: str,
        received_state: str,
        expected_state: str,
        verifier: str,
    ) -> dict[str, Any]:
        verify_state(expected_state, received_state)
        disc = await self.discovery.get_async()
        token_resp = await exchange_code_async(
            self.config, disc["token_endpoint"], code, verifier
        )
        # JwtVerifier uses sync httpx for JWKS — fine in async (fast)
        claims = self.jwt_verifier.verify(token_resp["access_token"])
        claims["_access_token"] = token_resp["access_token"]
        return claims
