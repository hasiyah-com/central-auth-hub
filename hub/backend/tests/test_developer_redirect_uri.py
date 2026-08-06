"""Tests — Redirect URI validation ตอนลงทะเบียน/แก้ subsystem (REQ-SUB-02, TC-SUB-03/04).

Zero-tolerance security item (test-design-document §3.6.3): open-redirect / javascript:
scheme ต้องถูกปฏิเสธตั้งแต่รับ input — ไม่ปล่อยเข้า DB. เดิม SubsystemCreate.redirect_uris
เป็น list[str] เปล่า ๆ ไม่มี validator → รับอะไรก็ได้.

ทดสอบระดับ Pydantic model (เร็ว ไม่ต้องผ่าน step-up gate). ครอบทั้ง Create + Update.
รัน: docker compose exec hub-backend pytest tests/test_developer_redirect_uri.py -v
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.routers.developer import SubsystemCreate, SubsystemUpdate


def _create(uris):
    return SubsystemCreate(name="x", redirect_uris=uris, scope=["email"])


# ── Positive (TC-SUB-03): URL ที่ถูกต้องผ่าน ──


def test_https_uri_accepted():
    m = _create(["https://dorm.example.com/callback"])
    assert m.redirect_uris == ["https://dorm.example.com/callback"]


def test_localhost_http_accepted_for_dev():
    """http อนุญาตเฉพาะ localhost/127.0.0.1 (dev)."""
    m = _create(["http://localhost:8001/oauth/callback"])
    assert m.redirect_uris[0].startswith("http://localhost")


def test_multiple_valid_uris_accepted():
    m = _create(["https://a.example.com/cb", "http://127.0.0.1:3000/auth/callback"])
    assert len(m.redirect_uris) == 2


# ── Negative (TC-SUB-04): URL อันตราย/ผิดรูปแบบ ถูกปฏิเสธ ──


@pytest.mark.parametrize(
    "bad",
    [
        "javascript:alert(document.cookie)",  # XSS scheme
        "data:text/html,<script>alert(1)</script>",  # data URI
        "ftp://files.example.com/x",  # ไม่ใช่ http/https
        "//evil.com/path",  # protocol-relative (ไม่มี scheme)
        "not-a-url",  # ไม่มี scheme/host
        "https://",  # ไม่มี host
        "",  # ว่าง
        "   ",  # whitespace ล้วน
    ],
)
def test_bad_redirect_uri_rejected(bad):
    with pytest.raises(ValidationError):
        _create([bad])


def test_http_non_localhost_rejected():
    """http กับ host จริง (ไม่ใช่ localhost) = ไม่ปลอดภัย (auth code ผ่าน plaintext)."""
    with pytest.raises(ValidationError):
        _create(["http://dorm.example.com/callback"])


def test_empty_redirect_list_rejected():
    with pytest.raises(ValidationError):
        _create([])


def test_one_bad_uri_in_list_rejects_whole():
    """มี URL เสียปนแม้แค่ 1 ตัว → reject ทั้ง request (ไม่บันทึกครึ่ง ๆ)."""
    with pytest.raises(ValidationError):
        _create(["https://ok.example.com/cb", "javascript:alert(1)"])


# ── Update ก็ต้อง validate เหมือนกัน (แก้ทีหลังก็ห้ามใส่ URL อันตราย) ──


def test_update_valid_uri_accepted():
    m = SubsystemUpdate(redirect_uris=["https://new.example.com/cb"])
    assert m.redirect_uris == ["https://new.example.com/cb"]


def test_update_bad_uri_rejected():
    with pytest.raises(ValidationError):
        SubsystemUpdate(redirect_uris=["javascript:alert(1)"])


def test_update_none_redirect_uris_ok():
    """Update ไม่ส่ง redirect_uris มา (None) = ไม่แก้ field นี้ → ผ่าน."""
    m = SubsystemUpdate(description="just a desc change")
    assert m.redirect_uris is None
