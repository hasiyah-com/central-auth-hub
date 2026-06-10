"""Token exchange — POST /oauth/token."""

from __future__ import annotations

import httpx

from .config import Config
from .errors import TokenError


def exchange_code(
    config: Config, token_endpoint: str, code: str, code_verifier: str
) -> dict:
    """Exchange auth code → access_token (server-to-server, sync)."""
    try:
        r = httpx.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "redirect_uri": config.redirect_uri,
                "code_verifier": code_verifier,
            },
            headers={"Accept": "application/json"},
            timeout=config.http_timeout,
        )
    except Exception as e:
        raise TokenError(f"Token endpoint unreachable: {e}") from e

    if r.status_code != 200:
        raise TokenError(f"Token exchange HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    if "access_token" not in data:
        raise TokenError("Response missing access_token")
    return data


async def exchange_code_async(
    config: Config, token_endpoint: str, code: str, code_verifier: str
) -> dict:
    """Async variant."""
    try:
        async with httpx.AsyncClient(timeout=config.http_timeout) as client:
            r = await client.post(
                token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": config.client_id,
                    "client_secret": config.client_secret,
                    "redirect_uri": config.redirect_uri,
                    "code_verifier": code_verifier,
                },
                headers={"Accept": "application/json"},
            )
    except Exception as e:
        raise TokenError(f"Token endpoint unreachable: {e}") from e
    if r.status_code != 200:
        raise TokenError(f"Token exchange HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    if "access_token" not in data:
        raise TokenError("Response missing access_token")
    return data
