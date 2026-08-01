"""Security tests — webhook SSRF guard (audit run-1, finding #2).

The Hub POSTs access-change notifications to subsystem.access_revoke_webhook_url,
a developer-controlled value. In production that URL must be https and must NOT
resolve to a private / loopback / link-local / reserved address (cloud metadata
169.254.169.254, internal docker services, RFC1918). Dev intentionally targets
localhost / docker-service names, so the guard only enforces in production.

รัน:
    docker compose exec hub-backend pytest tests/test_webhook_ssrf.py -v
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import webhook_dispatcher as wd


@pytest.fixture
def prod(monkeypatch):
    monkeypatch.setattr(wd.settings, "app_env", "production")


@pytest.fixture
def dev(monkeypatch):
    monkeypatch.setattr(wd.settings, "app_env", "development")


# ── _is_safe_webhook_url (prod enforcement) ─────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://169.254.169.254/latest/meta-data/",  # cloud metadata (link-local)
        "https://127.0.0.1/hook",  # loopback
        "https://10.0.0.5/hook",  # RFC1918 private
        "https://192.168.1.10/hook",  # RFC1918 private
        "http://93.184.216.34/hook",  # public IP but non-https
        "ftp://93.184.216.34/hook",  # wrong scheme
    ],
)
def test_prod_blocks_unsafe(prod, url):
    assert wd._is_safe_webhook_url(url) is False


def test_prod_allows_public_https(prod):
    # public IP literal, https → allowed
    assert (
        wd._is_safe_webhook_url("https://93.184.216.34/internal/access-updated") is True
    )


def test_dev_allows_localhost(dev):
    assert (
        wd._is_safe_webhook_url("http://localhost:8001/internal/access-updated") is True
    )


# ── _resolve_webhook_url returns None for unsafe target (centralized guard) ──


def _sub(url: str):
    return SimpleNamespace(
        id="sub-1",
        access_revoke_webhook_url=url,
        redirect_uris=["https://dorm.example.com/callback"],
        client_id="cli_x",
    )


def test_resolve_blocks_metadata_in_prod(prod):
    out = wd._resolve_webhook_url(
        _sub("https://169.254.169.254/x"), "/internal/access-updated"
    )
    assert out is None


def test_resolve_blocks_internal_service_in_prod(prod):
    out = wd._resolve_webhook_url(
        _sub("https://hub-postgres:5432/x"), "/internal/access-updated"
    )
    assert out is None


def test_resolve_allows_public_https_in_prod(prod):
    out = wd._resolve_webhook_url(
        _sub("https://93.184.216.34/internal/access-updated"),
        "/internal/access-updated",
    )
    assert out is not None and out.startswith("https://93.184.216.34")
