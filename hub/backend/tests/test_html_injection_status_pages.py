"""Security tests — HTML injection on subsystem status pages (audit run-1, finding #1).

`/oauth/authorize` (public) renders _suspended_html (status=suspended) and
_maintenance_html (health=down) with the subsystem name interpolated into an
f-string. The name is developer-controlled (set at registration). It MUST be
HTML-escaped — the sibling _login_chooser_html already does this. These tests
pin the escaping so it cannot regress.

รัน:
    docker compose exec hub-backend pytest tests/test_html_injection_status_pages.py -v
"""

from __future__ import annotations

from app.routers.oauth import (
    _login_chooser_html,
    _maintenance_html,
    _suspended_html,
)

XSS = "<script>alert(1)</script>"
ATTR = '"><img src=x onerror=alert(1)>'
META = '<meta http-equiv="refresh" content="0;url=https://evil.example">'


def _assert_escaped(html_out: str, raw: str) -> None:
    assert raw not in html_out, f"raw payload leaked: {raw!r}"
    assert "&lt;" in html_out and "&gt;" in html_out, "expected escaped angle brackets"


def test_suspended_html_escapes_name():
    out = _suspended_html(subsystem_name=XSS)
    _assert_escaped(out, XSS)


def test_suspended_html_escapes_meta_refresh():
    out = _suspended_html(subsystem_name=META)
    assert META not in out
    assert "http-equiv" not in out or "&lt;meta" in out


def test_maintenance_html_escapes_name():
    out = _maintenance_html(
        subsystem_name=ATTR, health={"error": "x", "checked_at": ""}
    )
    _assert_escaped(out, ATTR)
    assert "onerror=alert(1)>" not in out


def test_maintenance_html_escapes_health_error():
    """health['error'] is also interpolated raw — escape it too."""
    out = _maintenance_html(
        subsystem_name="ok", health={"error": XSS, "checked_at": ""}
    )
    assert XSS not in out
    assert "&lt;script&gt;" in out


def test_login_chooser_still_escapes_regression():
    """Sibling that was already correct — guard against regression."""
    out = _login_chooser_html(hub_state="s", subsystem_name=XSS, nonce="n")
    assert XSS not in out
    assert "&lt;script&gt;" in out
