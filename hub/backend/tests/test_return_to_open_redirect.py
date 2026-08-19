"""Open-redirect guard สำหรับ return_to ในหน้า passkey recover.

return_to ควรกลับไป login page ของ subsystem ที่ลงทะเบียนเท่านั้น — ไม่ใช่โดเมน
ภายนอกใดๆ (กันใช้โดเมน Hub เป็นจุดเด้ง phishing).

_safe_return_to():
  - relative path → อนุญาต
  - absolute http(s) → เฉพาะ origin ที่อยู่ใน allowlist (subsystem ที่ active)
  - นอกนั้น (evil.com, javascript:, //) → ทิ้ง

รัน:
    docker compose exec hub-backend pytest tests/test_return_to_open_redirect.py -v
"""

from __future__ import annotations

from app.routers.oauth import _safe_return_to

ALLOWED = {"https://dorm-iam.duckdns.org", "https://library-iam.duckdns.org"}


def test_allows_registered_subsystem_origin():
    url = "https://dorm-iam.duckdns.org/login"
    assert _safe_return_to(url, ALLOWED) == url


def test_allows_relative_path():
    assert _safe_return_to("/auth/login", ALLOWED) == "/auth/login"


def test_blocks_external_domain():
    # origin นอก allowlist → ต้องทิ้ง (นี่คือช่อง open-redirect เดิม)
    assert _safe_return_to("https://evil.com/phish", ALLOWED) == ""


def test_blocks_lookalike_host():
    # โดเมนหน้าตาคล้ายแต่ไม่ตรง origin → ทิ้ง
    assert _safe_return_to("https://dorm-iam.duckdns.org.evil.com/x", ALLOWED) == ""


def test_blocks_protocol_relative():
    assert _safe_return_to("//evil.com/x", ALLOWED) == ""


def test_blocks_dangerous_schemes():
    assert _safe_return_to("javascript:alert(1)", ALLOWED) == ""
    assert _safe_return_to("data:text/html,x", ALLOWED) == ""


def test_empty_returns_empty():
    assert _safe_return_to(None, ALLOWED) == ""
    assert _safe_return_to("", ALLOWED) == ""


def test_scheme_downgrade_not_in_allowlist_blocked():
    # allowlist มีแค่ https → http origin เดียวกันไม่ตรง → ทิ้ง
    assert _safe_return_to("http://dorm-iam.duckdns.org/login", ALLOWED) == ""
