"""B86: subsystem_id จาก authreq (JSON ใน Redis) เป็นสตริง แต่ profile ของ L2 เก็บเป็น UUID.

ผล: `subsystem_id not in seen_subsystems` จริงเสมอ → ทุก login เข้า subsystem ของผู้ใช้ที่มี
ประวัติ >= MIN_HISTORY_FOR_RARITY ได้ `new_subsystem +0.30 floor=challenge` แม้ใช้ระบบนั้นทุกวัน
→ ผู้ใช้ปกติบนเครื่องใหม่ได้ 0.9 ถูกบล็อกที่ finalizer (>= 0.85) ในโหมดบังคับใช้

เทสวิ่งผ่าน _finalize_subsystem_login จริง (authreq ผ่าน JSON เหมือน _load_authreq)
"""

from __future__ import annotations

import uuid

import pyotp
import pytest

from app.config import settings
from app.rate_limiter import limiter
from app.services import risk_challenge
from tests.finalize_env import (
    UA_NEW_DEVICE,
    add_owner_history,
    build_env,
    finalize,
    make_subsystem,
    random_test_ip,
    spy_risk,
    teardown_env,
)


@pytest.fixture(autouse=True)
def _enforce(monkeypatch):
    monkeypatch.setattr(settings, "ml_shadow_mode", False)
    prev = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = prev


@pytest.fixture
def ip():
    return random_test_ip()


@pytest.fixture
def env(db, ip):
    e = build_env(db)
    yield e
    teardown_env(db, e, ip)


def _has_new_subsystem(risk: dict) -> bool:
    return any(r.startswith("new_subsystem=") for r in risk["reasons"])


async def test_regular_subsystem_is_not_new_same_device(db, env, ip, monkeypatch):
    add_owner_history(db, env, ip)
    cap = spy_risk(monkeypatch)
    url = await finalize(db, env, ip)
    assert not _has_new_subsystem(cap["risk"]), cap["risk"]["reasons"]
    # ความเสี่ยงต่ำ → ได้ authorization code กลับ subsystem ตรงๆ ไม่ต้อง step-up
    assert url.startswith(env["authreq"]["redirect_uri"]), url
    assert "code=" in url


async def test_new_device_on_regular_subsystem_is_not_blocked(
    client, db, env, ip, monkeypatch
):
    add_owner_history(db, env, ip)
    cap = spy_risk(monkeypatch)
    url = await finalize(db, env, ip, ua=UA_NEW_DEVICE)  # ต้องไม่ raise 403
    assert not _has_new_subsystem(cap["risk"]), cap["risk"]["reasons"]
    assert cap["risk"]["score"] < settings.risk_block_hard_threshold
    # เครื่องใหม่ = challenge floor → step-up แล้วเข้าได้จริง
    assert url.startswith("/auth/passkey/risk-stepup?challenge="), url
    cid = url.split("challenge=", 1)[1]
    r = client.post(
        "/auth/passkey/risk-stepup/verify-totp",
        json={"challenge_id": cid, "code": pyotp.TOTP(env["secret"]).now()},
    )
    assert r.status_code == 200, r.text
    assert r.json()["redirect_url"].startswith(env["authreq"]["redirect_uri"])
    assert risk_challenge.peek(cid) is None


async def test_truly_new_subsystem_still_flagged(db, env, ip, monkeypatch):
    """การแก้ต้องไม่ปิดกฎ: ประวัติทั้งหมดอยู่ที่ระบบอื่น → ระบบนี้ยังเป็น new_subsystem."""
    other = make_subsystem(db, f"o{uuid.uuid4().hex[:6]}")
    env["extra_subs"].append(other)
    add_owner_history(db, env, ip, subsystem=other)
    cap = spy_risk(monkeypatch)
    await finalize(db, env, ip)
    assert _has_new_subsystem(cap["risk"]), cap["risk"]["reasons"]


async def test_l3_still_receives_legacy_string_until_separate_fix(
    db, env, ip, monkeypatch
):
    """ตรึงไว้โดยเจตนา: residual ของ L3 สะสมด้วยคีย์สตริง (count = 0 เสมอ) · เปลี่ยนชนิด
    = เปลี่ยนความหมายประวัติ L3 → ต้องทำเป็นงานแยกพร้อมเปลี่ยนคีย์/รุ่น (แบบ B84)
    เมื่อแก้ L3 แล้วให้ลบ/แก้เทสนี้
    """
    import app.security.risk_engine as re_mod

    seen = {}
    real = re_mod._evaluate_l3

    async def spy(user_id, features, profile, subsystem_id, *rest, **kw):
        seen["subsystem_id"] = subsystem_id
        return await real(user_id, features, profile, subsystem_id, *rest, **kw)

    monkeypatch.setattr(re_mod, "_evaluate_l3", spy)
    add_owner_history(db, env, ip)
    await finalize(db, env, ip)
    assert isinstance(seen["subsystem_id"], str)
