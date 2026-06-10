"""Config — validation."""

import pytest

from central_auth_hub.config import Config
from central_auth_hub.errors import HubError


class TestConfig:
    def test_valid_config(self):
        c = Config(
            hub_url="http://localhost:8000",
            client_id="cli_x",
            client_secret="sec_x",  # pragma: allowlist secret
            redirect_uri="http://localhost/cb",
        )
        assert c.hub_url == "http://localhost:8000"
        assert c.client_id == "cli_x"
        assert c.scope == ["openid", "profile", "email"]
        assert c.jwks_cache_ttl == 600

    def test_trailing_slash_stripped(self):
        c = Config(
            hub_url="http://localhost:8000/",
            client_id="x",
            client_secret="y",  # pragma: allowlist secret
            redirect_uri="z",
        )
        assert c.hub_url == "http://localhost:8000"

    def test_missing_client_id_raises(self):
        with pytest.raises(HubError, match="client_id"):
            Config(
                hub_url="http://x",
                client_id="",
                client_secret="y",  # pragma: allowlist secret
                redirect_uri="z",
            )

    def test_custom_scope(self):
        c = Config(
            hub_url="http://x",
            client_id="x",
            client_secret="y",  # pragma: allowlist secret
            redirect_uri="z",
            scope=["email", "student_id"],
        )
        assert c.scope == ["email", "student_id"]
