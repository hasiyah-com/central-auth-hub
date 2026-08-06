"""Security tests — get_client_ip spoofing resistance + dev-endpoint prod guard.

ครอบ 2 ช่องโหว่ที่แก้ (2026-07-28):
  #2 X-Forwarded-For spoofing — get_client_ip เคยเอา XFF[0] (client คุมได้)
     → ปลอมประเทศ/เลี่ยง GeoIP risk/bypass IP blacklist/ปลอม audit log
  #1 dev endpoints (/oauth/pkce-helper, /oauth/test-callback) — reflected XSS +
     ควรปิดใน production

รัน:
    docker compose exec hub-backend pytest tests/test_client_ip_security.py -v
"""

from __future__ import annotations

from types import SimpleNamespace

from starlette.datastructures import Headers

from app.deps import get_client_ip


def _req(headers: dict | None = None, client_host: str | None = "172.18.0.1"):
    """Request จำลอง — get_client_ip ใช้แค่ .headers.get() + .client.host."""
    return SimpleNamespace(
        headers=Headers(headers or {}),
        client=SimpleNamespace(host=client_host) if client_host else None,
    )


# ── #2 X-Forwarded-For spoofing resistance ──────────────────────────────────


def test_xff_takes_rightmost_not_client_controlled_leftmost():
    """client ปลอม IP ไว้ซ้ายสุด, proxy เติม IP จริงไว้ขวาสุด → ต้องได้ตัวขวาสุด."""
    r = _req({"x-forwarded-for": "6.6.6.6, 203.0.113.9"})
    assert get_client_ip(r) == "203.0.113.9", "ต้องเอา IP ที่ proxy เติม ไม่ใช่ที่ client ปลอม"


def test_xff_multi_hop_takes_last():
    r = _req({"x-forwarded-for": "1.1.1.1, 2.2.2.2, 203.0.113.9"})
    assert get_client_ip(r) == "203.0.113.9"


def test_x_real_ip_preferred_over_xff():
    """nginx set X-Real-IP = remote_addr (client ทับไม่ได้) → ใช้ก่อน XFF."""
    r = _req({"x-real-ip": "203.0.113.9", "x-forwarded-for": "6.6.6.6"})
    assert get_client_ip(r) == "203.0.113.9"


def test_spoofed_leftmost_alone_still_from_proxy():
    """XFF ค่าเดียว = ที่ proxy set (single-hop) → ใช้ได้ (rightmost==only)."""
    r = _req({"x-forwarded-for": "203.0.113.9"})
    assert get_client_ip(r) == "203.0.113.9"


def test_garbage_xff_falls_back_to_client_host():
    """XFF ไม่ใช่ IP (garbage/log-injection) → fallback ไป client.host."""
    r = _req({"x-forwarded-for": "not-an-ip"}, client_host="203.0.113.9")
    assert get_client_ip(r) == "203.0.113.9"


def test_direct_no_proxy_uses_client_host():
    """dev/docker — ไม่มี proxy header → request.client.host."""
    r = _req({}, client_host="172.18.0.1")
    assert get_client_ip(r) == "172.18.0.1"


def test_ipv4_mapped_ipv6_normalized():
    r = _req({"x-real-ip": "::ffff:203.0.113.9"})
    assert get_client_ip(r) == "203.0.113.9"


def test_no_ip_anywhere_returns_none():
    r = _req({}, client_host=None)
    assert get_client_ip(r) is None


# ── #1 dev endpoints — XSS escape + prod guard ──────────────────────────────


def test_test_callback_escapes_xss(client):
    """code/state (query param) ต้องถูก escape — กัน reflected XSS."""
    payload = "<script>alert(1)</script>"
    r = client.get("/oauth/test-callback", params={"code": payload})
    assert r.status_code == 200
    assert payload not in r.text  # raw script ต้องไม่หลุด
    assert "&lt;script&gt;" in r.text  # ถูก escape แล้ว


def test_test_callback_escapes_attribute_breakout(client):
    r = client.get(
        "/oauth/test-callback", params={"state": '"><img src=x onerror=alert(1)>'}
    )
    assert "onerror=alert(1)>" not in r.text
    assert "&quot;&gt;&lt;img" in r.text


def test_dev_endpoints_blocked_in_production(client, monkeypatch):
    """pkce-helper / test-callback → 404 ใน production (ไม่ leak ว่ามี endpoint)."""
    from app.config import settings

    monkeypatch.setattr(settings, "app_env", "production")
    assert client.get("/oauth/pkce-helper").status_code == 404
    assert client.get("/oauth/test-callback").status_code == 404


def test_dev_endpoints_available_in_dev(client, monkeypatch):
    """dev/development → เข้าถึงได้ปกติ."""
    from app.config import settings

    monkeypatch.setattr(settings, "app_env", "development")
    assert client.get("/oauth/pkce-helper").status_code == 200


# ── #3 CSP form-action (กัน form submit ออกนอก origin) ──────────────────────


def test_csp_has_form_action_on_hub_served_page(client):
    """หน้า HTML ที่ Hub render (nonce route) ต้องมี form-action 'self'."""
    r = client.get("/oauth/test-callback", params={"code": "x"})
    csp = r.headers.get("content-security-policy", "")
    assert "form-action 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_csp_has_form_action_on_api_route(client):
    """API route ทั่วไป (non-nonce) ก็ต้องมี form-action 'self'."""
    r = client.get("/health")
    csp = r.headers.get("content-security-policy", "")
    assert "form-action 'self'" in csp
