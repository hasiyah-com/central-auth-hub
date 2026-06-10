"""End-to-end integration with running Hub backend at http://localhost:8000.

Requires:
  - Hub backend container running
  - Token issued via docker exec (test fixture)
"""

import os
import subprocess

import pytest

from central_auth_hub import HubClient
from central_auth_hub.config import Config
from central_auth_hub.discovery import Discovery
from central_auth_hub.errors import JwtError
from central_auth_hub.jwt_verifier import JwtVerifier

HUB = "http://localhost:8000"
CLIENT_ID = "cli_1ded036e86ec4c1b"


def _get_real_token() -> str:
    """Issue a test JWT via docker exec."""
    env = os.environ.get("TEST_HUB_TOKEN")
    if env:
        return env
    cmd = [
        "docker",
        "exec",
        "hub-backend",
        "python",
        "-c",
        (
            "from app.database import SessionLocal;"
            "from app.models import User, Subsystem, AccessList;"
            "from app.services.jwt_service import create_subsystem_token;"
            "db=SessionLocal();"
            "user=db.query(User).filter(User.email.like('%@uni.ac.th')).first();"
            "sub=db.query(Subsystem).filter(Subsystem.client_id=='cli_1ded036e86ec4c1b').first();"
            "al=db.query(AccessList).filter(AccessList.subsystem_id==sub.id, AccessList.revoked_at.is_(None)).first();"
            "tok,_=create_subsystem_token(user, sub.client_id, ['openid','profile','email'], al.role_in_sub if al else 'user');"
            "print(tok, end='')"
        ),
    ]
    try:
        out = subprocess.check_output(cmd, text=True, timeout=10)
    except Exception:
        pytest.skip("docker not available")
    if not out or out.count(".") != 2:
        pytest.skip("could not get valid token")
    return out


@pytest.fixture
def real_token():
    return _get_real_token()


@pytest.fixture
def config():
    return Config(
        hub_url=HUB,
        client_id=CLIENT_ID,
        client_secret="dummy",  # pragma: allowlist secret
        redirect_uri="http://localhost/cb",
    )


class TestIntegration:
    def test_discovery_loads(self, config):
        disc = Discovery(config).get()
        assert disc["issuer"] == "https://hub.local"
        assert "openid" in disc["scopes_supported"]
        assert "profile" in disc["scopes_supported"]
        assert "RS256" in disc["id_token_signing_alg_values_supported"]
        assert "S256" in disc["code_challenge_methods_supported"]

    def test_jwt_verifier_accepts_real_token(self, config, real_token):
        jv = JwtVerifier(config, Discovery(config))
        claims = jv.verify(real_token)
        assert claims["aud"] == CLIENT_ID
        assert claims["iss"] == "https://hub.local"
        assert "sub" in claims
        assert "email" in claims
        assert "exp" in claims
        assert "jti" in claims

    def test_jwt_verifier_rejects_tampered(self, config, real_token):
        parts = real_token.split(".")
        tampered = parts[0] + "." + parts[1] + ".AAAAAA"
        jv = JwtVerifier(config, Discovery(config))
        with pytest.raises(JwtError):
            jv.verify(tampered)

    def test_jwt_verifier_rejects_wrong_audience(self, real_token):
        wrong_cfg = Config(
            hub_url=HUB,
            client_id="cli_other_subsystem",
            client_secret="x",  # pragma: allowlist secret
            redirect_uri="z",
        )
        jv = JwtVerifier(wrong_cfg, Discovery(wrong_cfg))
        with pytest.raises(JwtError):
            jv.verify(real_token)

    def test_build_authorize_url(self):
        hub = HubClient(
            hub_url=HUB,
            client_id=CLIENT_ID,
            client_secret="x",  # pragma: allowlist secret
            redirect_uri="http://localhost/cb",
        )
        url, state, verifier = hub.build_authorize_url()
        assert "/oauth/authorize?" in url
        assert "response_type=code" in url
        assert "code_challenge_method=S256" in url
        assert f"client_id={CLIENT_ID}" in url
        assert "scope=openid+profile+email" in url
        assert len(state) == 32
        assert 43 <= len(verifier) <= 128


class TestAsyncIntegration:
    async def test_discovery_async_loads(self, config):
        disc = await Discovery(config).get_async()
        assert disc["issuer"] == "https://hub.local"

    async def test_build_authorize_url_async(self):
        hub = HubClient(
            hub_url=HUB,
            client_id=CLIENT_ID,
            client_secret="x",  # pragma: allowlist secret
            redirect_uri="http://localhost/cb",
        )
        url, state, verifier = await hub.build_authorize_url_async()
        assert "/oauth/authorize?" in url
        assert len(state) == 32
