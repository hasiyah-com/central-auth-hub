"""Config — validate + hold SDK settings."""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import HubError


@dataclass(frozen=True)
class Config:
    hub_url: str
    client_id: str
    client_secret: str
    redirect_uri: str
    scope: list[str] = field(default_factory=lambda: ["openid", "profile", "email"])
    jwks_cache_ttl: int = 600  # seconds
    http_timeout: float = 10.0

    def __post_init__(self):
        for k in ("hub_url", "client_id", "client_secret", "redirect_uri"):
            if not getattr(self, k):
                raise HubError(f"Config: missing required '{k}'")
        # strip trailing slash
        object.__setattr__(self, "hub_url", self.hub_url.rstrip("/"))
