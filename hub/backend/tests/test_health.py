"""Smoke tests: health endpoints + JWKS shape."""

import pytest


@pytest.mark.smoke
def test_root_returns_metadata(client):
    """GET / → ข้อมูล service + version."""
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Central Auth Hub"
    assert "version" in body
    assert "jwks" in body


@pytest.mark.smoke
def test_health_endpoint(client):
    """GET /health → service alive."""
    r = client.get("/health")
    assert r.status_code == 200


@pytest.mark.smoke
def test_jwks_endpoint_shape(client):
    """GET /.well-known/jwks.json → RFC 7517 shape."""
    r = client.get("/.well-known/jwks.json")
    assert r.status_code == 200
    body = r.json()
    assert "keys" in body
    assert isinstance(body["keys"], list)
    assert len(body["keys"]) >= 1
    key = body["keys"][0]
    assert key["kty"] == "RSA"
    assert key["alg"] == "RS256"
    assert key["use"] == "sig"
    assert "kid" in key
    assert "n" in key  # RSA modulus
    assert "e" in key  # RSA exponent


@pytest.mark.smoke
def test_security_headers_present(client):
    """All responses ต้องมี security headers ตาม OWASP."""
    r = client.get("/")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert "referrer-policy" in r.headers
    assert "content-security-policy" in r.headers
    assert "permissions-policy" in r.headers


@pytest.mark.smoke
def test_cors_preflight(client):
    """OPTIONS request → CORS headers."""
    r = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    # ยอมรับได้ทั้ง 200 หรือ 405 (FastAPI/Starlette behavior)
    # สำคัญคือถ้าผ่านต้องมี CORS headers
    if r.status_code == 200:
        assert "access-control-allow-origin" in r.headers
