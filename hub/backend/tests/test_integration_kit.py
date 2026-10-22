from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime

import pytest

from app.services import email_service
from app.services.integration_kit import build_integration_kit


def _kit(**overrides):
    values = {
        "subsystem_name": "Dormitory",
        "client_id": "client-123",
        "redirect_uris": ["https://dorm.example.ac.th/auth/callback"],
        "scopes": ["openid", "email", "profile"],
        "issuer": "https://auth.example.ac.th",
        "hub_base_url": "https://auth.example.ac.th/",
    }
    values.update(overrides)
    return build_integration_kit(**values)


def test_kit_contains_env_registration_and_thai_guide_without_secret():
    kit = _kit()
    with zipfile.ZipFile(io.BytesIO(kit.content)) as archive:
        assert set(archive.namelist()) == {
            ".env.example",
            "registration.json",
            "README_TH.md",
        }
        env = archive.read(".env.example").decode()
        registration = json.loads(archive.read("registration.json"))
        guide = archive.read("README_TH.md").decode()

    assert 'CENTRAL_AUTH_CLIENT_ID="client-123"' in env
    assert 'CENTRAL_AUTH_INTERNAL_URL="https://auth.example.ac.th"' in env
    assert 'CENTRAL_AUTH_PUBLIC_URL="https://auth.example.ac.th"' in env
    assert "replace-with-the-secret-from-the-one-time-email-link" in env
    assert registration["redirect_uris"] == [
        "https://dorm.example.ac.th/auth/callback"
    ]
    assert registration["token_endpoint"] == "https://auth.example.ac.th/oauth/token"
    assert "ห้ามใส่ Client Secret" in guide


@pytest.mark.parametrize("bad", ["x\nINJECTED=yes", "x\rINJECTED=yes", "x\x00y"])
def test_kit_rejects_env_line_injection(bad):
    with pytest.raises(ValueError):
        _kit(client_id=bad)


def test_kit_filename_is_safe():
    kit = _kit(subsystem_name="../../Dorm ระบบ")
    assert "/" not in kit.filename
    assert "\\" not in kit.filename
    assert kit.filename.endswith("-integration.zip")


def test_registration_email_links_secret_and_portal_and_shows_redirect(monkeypatch):
    captured = {}

    def fake_send(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(email_service, "_send_html_email", fake_send)
    assert email_service.send_secret_retrieval_email(
        to_email="dev@example.ac.th",
        subsystem_name="Dormitory",
        retrieval_url="https://auth.example.ac.th/secret/retrieve?token=one-time",
        expires_at=datetime(2026, 10, 22, 12, 0),
        client_id="client-123",
        redirect_uris=["https://dorm.example.ac.th/auth/callback"],
        portal_url="https://hub.example.ac.th/developer/subsystems/sub-1",
    )

    html = captured["html"]
    text = captured["text_fallback"]
    assert "client-123" in html and "client-123" in text
    assert "https://dorm.example.ac.th/auth/callback" in html and "https://dorm.example.ac.th/auth/callback" in text
    assert "https://hub.example.ac.th/developer/subsystems/sub-1" in html and "https://hub.example.ac.th/developer/subsystems/sub-1" in text
    assert "token=one-time" in html and "token=one-time" in text


def test_registration_email_escapes_html(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        email_service,
        "_send_html_email",
        lambda **kwargs: captured.update(kwargs) or True,
    )
    email_service.send_secret_retrieval_email(
        to_email="dev@example.ac.th",
        subsystem_name='<img src=x onerror="alert(1)">',
        retrieval_url="https://auth.example/retrieve?a=1&b=2",
        expires_at=datetime(2026, 10, 22, 12, 0),
        client_id="client<unsafe>",
        redirect_uris=["https://example.test/cb?a=1&b=2"],
        portal_url="https://hub.example/developer?a=1&b=2",
    )
    html = captured["html"]
    assert "<img src=x" not in html
    assert "client&lt;unsafe&gt;" in html
    assert "a=1&amp;b=2" in html
