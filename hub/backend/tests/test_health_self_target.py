"""Health check — subsystem ที่ชี้ redirect_uri กลับมาที่ Hub เอง ต้องไม่ขึ้น "online" (B60).

อาการที่เจอจริง: subsystem ทดสอบตั้ง `redirect_uri = http://localhost:3000/developer/...`
(= หน้าคอนโซลของ Hub เอง) แล้ว dashboard รายงาน **online 584ms** ทั้งที่ไม่ใช่ระบบย่อย —
เพราะ health check ยิง `localhost:3000/health` → Next.js rewrite ส่งต่อเข้า `hub-backend`
ตาม single-domain mode → ได้ 200 กลับมาจาก *ตัว Hub เอง*

ผล: "1/6 healthy" บน dashboard โดยตัวที่ healthy ตัวเดียวคือตัวปลอม (false positive)

Fix: `_ping` เช็ค origin เทียบกับ origin ของ Hub เอง (hub_base_url / admin_frontend_url /
service name ใน docker) → คืน `unknown` + `self_target=True` แทนที่จะยิงจริง

รัน: docker compose exec hub-backend pytest tests/test_health_self_target.py -v
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import settings
from app.services.subsystem_health import (
    _origin_key,
    _ping,
    _self_origin_keys,
)


def _fake_sub(redirect_uri: str) -> SimpleNamespace:
    """subsystem จำลอง — _ping ใช้แค่ .redirect_uris กับ .id"""
    return SimpleNamespace(
        id="00000000-0000-0000-0000-0000000000ff", redirect_uris=[redirect_uri]
    )


# ─── _origin_key: normalize (host, port) ────────────────────────────────────


def test_origin_key_fills_default_port_by_scheme():
    assert _origin_key("http://example.com/health") == ("example.com", "80")
    assert _origin_key("https://example.com/health") == ("example.com", "443")
    assert _origin_key("http://example.com:8003/x") == ("example.com", "8003")


def test_origin_key_is_case_insensitive_on_host():
    assert _origin_key("http://LocalHost:3000") == _origin_key("http://localhost:3000")


def test_origin_key_returns_none_for_garbage():
    assert _origin_key("") is None
    assert _origin_key("://///") is None


# ─── _self_origin_keys: ต้องครอบ Hub + console ทั้ง raw และ docker-translated ──


def test_self_origins_include_hub_and_console():
    keys = _self_origin_keys()
    assert _origin_key(settings.hub_base_url) in keys
    assert _origin_key(settings.admin_frontend_url) in keys


def test_self_origins_include_docker_service_names():
    keys = _self_origin_keys()
    assert ("hub-backend", "8000") in keys
    assert ("hub-frontend", "3000") in keys


def test_real_subsystem_origin_is_not_self():
    """ระบบย่อยจริง (คนละ origin) ต้องไม่ถูกมองว่าเป็น Hub — ไม่งั้นเช็คไม่ได้ทั้งระบบ."""
    keys = _self_origin_keys()
    for uri in (
        "http://localhost:8001/oauth/callback",  # dorm
        "http://localhost:8002/oauth/callback",  # library
        "http://localhost:8003/oauth/callback",  # grade
        "https://dorm.example.ac.th/oauth/callback",
    ):
        assert _origin_key(uri) not in keys, f"{uri} ไม่ควรถูกนับเป็น Hub เอง"


# ─── _ping: self-target → unknown (ไม่ยิงเน็ตเลย) ───────────────────────────


@pytest.mark.asyncio
async def test_ping_flags_console_origin_as_self_target():
    """redirect_uri = หน้าคอนโซล → unknown + self_target (เดิมได้ online หลอก)."""
    res = await _ping(
        _fake_sub(f"{settings.admin_frontend_url}/developer/subsystems/new")
    )
    assert res["status"] == "unknown"
    assert res.get("self_target") is True
    assert "redirect_uri" in res["error"]


@pytest.mark.asyncio
async def test_ping_flags_hub_backend_origin_as_self_target():
    """redirect_uri = Hub backend เอง → unknown เช่นกัน."""
    res = await _ping(_fake_sub(f"{settings.hub_base_url}/oauth/callback"))
    assert res["status"] == "unknown"
    assert res.get("self_target") is True


@pytest.mark.asyncio
async def test_ping_does_not_flag_real_subsystem():
    """ระบบย่อยจริงต้องไม่ติด guard — เดินหน้าเช็คจริง (ผลจะ online/down แล้วแต่ container).

    ยืนยันแค่ว่า "ไม่ใช่ self_target" พอ — สถานะจริงขึ้นกับว่า container รันอยู่ไหม
    """
    res = await _ping(_fake_sub("http://localhost:8001/oauth/callback"))
    assert res.get("self_target") is not True
    assert res["status"] in ("online", "degraded", "down", "unknown")
