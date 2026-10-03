"""Lockout DoS: ความล้มเหลวที่ใครก็สร้างได้ด้วยอีเมลอย่างเดียว ต้องไม่บล็อกเจ้าของบัญชี.

provenance ของ action ที่ failed_logins_24h นับ (ตรวจจากโค้ด 2026-09-26):
  - passkey_login_failed · oauth_passkey_login_failed — endpoint เปิด ต้องรู้แค่ email
    (oauth ต้องมี hub_state ซึ่งใครก็ขอจาก /oauth/authorize ได้) → ผู้โจมตีสร้างได้
  - passkey_stepup_failed · stepup_otp_failed · stepup_totp_failed — ต้องมี Hub JWT
  - risk_mfa_verify_failed · risk_force_enroll_otp_failed — ต้องมี challenge_id
    ที่ออกหลังผ่านปัจจัยแรกแล้วเท่านั้น

กฎที่ต้องการ: ความล้มเหลวที่ผูกด้วยอีเมลให้แค่ challenge floor ไม่บวกคะแนน · บล็อกเมื่อ
ความล้มเหลวหลังผ่านปัจจัยแรกถึงเกณฑ์ · สัญญาณรุนแรงอื่นยังบล็อกตามกฎของตัวเอง

เทสวิ่งเส้นเต็มกับเจ้าของบัญชีที่มีประวัติ 20 วัน: _finalize_subsystem_login (โหมดบังคับใช้)
→ ออก challenge → ใช้ challenge ด้วย TOTP → ได้ authorization code กลับ subsystem
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pyotp
import pytest
from fastapi import HTTPException

from app.config import settings
from app.models import AuditLog, IpBlacklist, LoginSession
from app.rate_limiter import limiter
from app.services import risk_challenge
from tests.finalize_env import (
    UA_NEW_DEVICE,
    UA_OWNER,
    add_owner_history,
    build_env,
    finalize,
    random_test_ip,
    spy_risk,
    teardown_env,
)

N_ATTACK = 12  # เกินเกณฑ์บล็อก (>= 10)


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
    add_owner_history(db, e, ip)
    yield e
    teardown_env(db, e, ip)


def _email_only_failures(db, user, n=N_ATTACK):
    """ผู้โจมตีรู้แค่อีเมล: passkey login ผิดซ้ำ (actor_id NULL · ผูกด้วย email)."""
    now = datetime.utcnow()
    for i in range(n):
        action = "passkey_login_failed" if i % 2 else "oauth_passkey_login_failed"
        db.add(
            AuditLog(
                actor_id=None,
                action=action,
                target_type="passkey",
                target_id=user.id,  # ให้ cleanup ลบได้ · ไม่มีผลต่อการนับ
                ip="192.0.2.66",
                metadata_json={"email": user.email, "code": "invalid"},
                created_at=now - timedelta(minutes=30 + i),
            )
        )
    db.commit()


def _post_factor_failures(db, user, n=N_ATTACK):
    now = datetime.utcnow()
    for i in range(n):
        db.add(
            AuditLog(
                actor_id=user.id,
                action="stepup_totp_failed",
                target_type="user",
                target_id=user.id,
                metadata_json={"method": "totp"},
                created_at=now - timedelta(minutes=30 + i),
            )
        )
    db.commit()


def _failed_score_reasons(risk: dict) -> list[str]:
    return [r for r in risk["reasons"] if r.startswith("failed_logins_24h (+")]


def _redeem(client, env, url: str) -> None:
    """ใช้ challenge จริงด้วย TOTP ของเจ้าของบัญชี → ต้องได้ code กลับ subsystem."""
    assert url.startswith("/auth/passkey/risk-stepup?challenge="), url
    cid = url.split("challenge=", 1)[1]
    payload = risk_challenge.peek(cid)
    assert payload and payload["user_id"] == str(env["user"].id)
    r = client.post(
        "/auth/passkey/risk-stepup/verify-totp",
        json={"challenge_id": cid, "code": pyotp.TOTP(env["secret"]).now()},
    )
    assert r.status_code == 200, r.text
    redirect = r.json()["redirect_url"]
    assert redirect.startswith(env["authreq"]["redirect_uri"])
    assert "code=" in redirect
    assert risk_challenge.peek(cid) is None  # consume แล้ว


# ── สี่กรณีที่วัดไว้ (เจ้าของบัญชีมีประวัติ) ──────────────────────────────────


async def test_control_same_device_passes(db, env, ip, monkeypatch):
    cap = spy_risk(monkeypatch)
    url = await finalize(db, env, ip, ua=UA_OWNER)
    assert url.startswith(env["authreq"]["redirect_uri"]), cap["risk"]["reasons"]


async def test_control_new_device_without_attack_avoids_redundant_challenge(
    client, db, env, ip, monkeypatch
):
    cap = spy_risk(monkeypatch)
    url = await finalize(db, env, ip, ua=UA_NEW_DEVICE)
    assert cap["risk"]["score"] < settings.risk_block_hard_threshold
    assert cap["risk"]["decision"] == "warn"
    assert url.startswith(env["authreq"]["redirect_uri"]), url
    assert "code=" in url


async def test_email_only_attack_same_device_gets_usable_challenge(
    client, db, env, ip, monkeypatch
):
    _email_only_failures(db, env["user"])
    cap = spy_risk(monkeypatch)
    url = await finalize(db, env, ip, ua=UA_OWNER)  # ต้องไม่ raise 403
    assert _failed_score_reasons(cap["risk"]) == [], cap["risk"]["reasons"]
    assert cap["risk"]["score"] < settings.risk_block_hard_threshold
    _redeem(client, env, url)


async def test_email_only_attack_new_device_gets_usable_challenge(
    client, db, env, ip, monkeypatch
):
    _email_only_failures(db, env["user"])
    cap = spy_risk(monkeypatch)
    url = await finalize(db, env, ip, ua=UA_NEW_DEVICE)  # ต้องไม่ raise 403
    assert _failed_score_reasons(cap["risk"]) == [], cap["risk"]["reasons"]
    assert cap["risk"]["score"] < settings.risk_block_hard_threshold
    _redeem(client, env, url)


# ── ยังต้องบล็อก ─────────────────────────────────────────────────────────────


async def test_post_factor_failures_still_block(db, env, ip):
    _post_factor_failures(db, env["user"])
    with pytest.raises(HTTPException) as ei:
        await finalize(db, env, ip)
    assert ei.value.status_code == 403


async def test_email_only_plus_login_burst_still_blocks(db, env, ip):
    """login_count_24h >= 50 เป็น hard block ในลูปเดียวกับ failed_logins_24h."""
    _email_only_failures(db, env["user"])
    now = datetime.utcnow()
    for i in range(55):
        db.add(
            LoginSession(
                user_id=env["user"].id,
                ip=ip,
                user_agent=UA_OWNER,
                decision="allow",
                subsystem_id=env["sub"].id,
                created_at=now - timedelta(minutes=5 + i * 10),
            )
        )
    db.commit()
    with pytest.raises(HTTPException) as ei:
        await finalize(db, env, ip)
    assert ei.value.status_code == 403


async def test_email_only_plus_blacklisted_ip_still_blocks(db, env, ip):
    _email_only_failures(db, env["user"])
    db.add(IpBlacklist(ip_address=ip, reason="test"))
    db.commit()
    with pytest.raises(HTTPException) as ei:
        await finalize(db, env, ip)
    assert ei.value.status_code == 403


# ── ไม่มีทางคะแนนอื่นจากความล้มเหลวแบบรู้อีเมลอย่างเดียว ─────────────────────


@pytest.mark.parametrize("ua", [UA_OWNER, UA_NEW_DEVICE])
async def test_email_only_failures_add_no_score_on_any_layer(db, env, ip, ua):
    """บริบทเดียวกัน ก่อน/หลังโจมตี: คะแนนรวม (L1+L2+L4) และทุกชั้นต้องเท่าเดิม ·
    ต่างกันได้แค่ challenge floor — ผู้โจมตีดันคะแนนเข้าใกล้เกณฑ์บล็อกไม่ได้
    """
    import uuid as _uuid

    from app.security.risk_engine import evaluate_login_risk
    from app.services.feature_extraction import extract_session_features

    sub_id = _uuid.UUID(env["authreq"]["subsystem_id"])

    async def _score():
        f = extract_session_features(
            db, env["user"].id, ip, ua, None, subsystem_id=sub_id
        )
        return await evaluate_login_risk(
            f,
            str(env["user"].id),
            ip,
            None,
            db,
            shadow_mode=False,
            subsystem_id=sub_id,
            user_agent=ua,
        )

    before = await _score()
    _email_only_failures(db, env["user"])
    after = await _score()

    assert after["score"] == before["score"], (before["reasons"], after["reasons"])
    for layer in ("rule", "behavior", "iforest"):
        assert after["breakdown"][layer] == before["breakdown"][layer], layer
    assert after["decision"] in ("challenge", "block") and after["decision"] != "block"


async def test_few_email_only_failures_add_no_score(db, env, ip):
    """3-4 ครั้ง (ใต้ floor ≥ 5) ก็ต้องไม่บวกคะแนนจากกฎ ≥ 3 ให้ผู้โจมตี."""
    import uuid as _uuid

    from app.security.risk_engine import evaluate_login_risk
    from app.services.feature_extraction import extract_session_features

    sub_id = _uuid.UUID(env["authreq"]["subsystem_id"])

    async def _score():
        f = extract_session_features(
            db, env["user"].id, ip, UA_NEW_DEVICE, None, subsystem_id=sub_id
        )
        return await evaluate_login_risk(
            f,
            str(env["user"].id),
            ip,
            None,
            db,
            shadow_mode=False,
            subsystem_id=sub_id,
            user_agent=UA_NEW_DEVICE,
        )

    before = await _score()
    _email_only_failures(db, env["user"], n=4)
    after = await _score()
    assert after["score"] == before["score"], after["reasons"]
    assert _failed_score_reasons(after) == []


# ── โหมดของ rule engine: กฎปัจจุบัน vs ทำซ้ำผล freeze ──────────────────────────


def _vec(failed: float) -> list[float]:
    from app.security.rule_engine import FEAT

    f = [0.0] * (max(FEAT.values()) + 1)
    f[FEAT["failed_logins_24h"]] = failed
    return f


@pytest.mark.parametrize("failed", [3.0, 6.0, 12.0])
def test_current_rules_without_db_refuse_instead_of_legacy(failed):
    """กฎปัจจุบันต้องแยก provenance จาก audit_logs · ไม่มี DB → หยุดพร้อมสาเหตุ
    ห้ามแอบตกไปใช้กฎเดิม (สคริปต์ทดลองจะรายงานผิดว่าเป็นกฎ production)
    """
    from app.security.rule_engine import RuleEvaluationError, evaluate_rules

    with pytest.raises(RuleEvaluationError, match="legacy_replay"):
        evaluate_rules(_vec(failed), db=None, user_id="u", ip=None, geo_country=None)


def test_current_rules_without_db_ok_when_failures_not_needed():
    from app.security.rule_engine import evaluate_rules

    res = evaluate_rules(_vec(2.0), db=None, user_id="u", ip=None, geo_country=None)
    assert res.rule_mode == "current"
    assert res.blocked is False


def test_legacy_replay_matches_frozen_rule_engine_exactly():
    """legacy_replay ต้องให้ผลเหมือนซอร์ส rule_engine ที่ tag rba-freeze-2026-08-29 ทุกช่อง
    (golden 611 เวกเตอร์ จาก scripts/make_rule_engine_legacy_golden_2026-09-26.py) ·
    ผลติด rule_mode="legacy_replay" เสมอ
    """
    import json
    from pathlib import Path

    from app.security.rule_engine import evaluate_rules

    golden = json.loads(
        (
            Path(__file__).parent / "data/rule_engine_legacy_golden_2026-08-29.json"
        ).read_text(encoding="utf-8")
    )
    assert golden["source"].startswith("rba-freeze-2026-08-29:")
    assert len(golden["cases"]) >= 600
    for case in golden["cases"]:
        r = evaluate_rules(
            case["features"],
            db=None,
            user_id="u",
            ip=None,
            geo_country=None,
            mode="legacy_replay",
        )
        assert r.rule_mode == "legacy_replay"
        assert (r.blocked, r.score, r.reasons, r.min_action) == (
            case["blocked"],
            case["score"],
            case["reasons"],
            case["min_action"],
        ), case["features"]


def test_unknown_rule_mode_rejected():
    from app.security.rule_engine import evaluate_rules

    with pytest.raises(ValueError):
        evaluate_rules(
            _vec(0.0), db=None, user_id="u", ip=None, geo_country=None, mode="x"
        )
