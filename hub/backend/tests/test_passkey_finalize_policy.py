"""Regression — passkey re-auth finalizer ต้อง honor access policy (B59).

`_finalize_after_reauth` (passkey.py) เดิมเช็คสิทธิ์ด้วย **raw AccessList lookup**
(ต้องมี allow row) → subsystem policy ที่ไม่มี row เลย (all/role/attribute) โดน
403 "ไม่มีสิทธิ์เข้า subsystem นี้" ทั้งที่ user ผ่านด่านแรก (OAuth entry ใช้
evaluate_access_policy) มาแล้ว — เจอตอน force-enroll passkey เสร็จแล้วโดนเด้ง.

Fix: ใช้ evaluate_access_policy ตัวเดียวกับ OAuth entry → honor ทุก policy.

เรียก `_finalize_after_reauth` ตรง ๆ (ครอบทั้ง 3 flow: risk-stepup / OTP / force-enroll
ที่ route ผ่านฟังก์ชันเดียวกัน).

รัน: docker compose exec hub-backend pytest tests/test_passkey_finalize_policy.py -v
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.database import SessionLocal
from app.models import AuditLog, LoginSession, Subsystem, User
from app.redis_client import redis_client
from app.routers.passkey import _finalize_after_reauth


def _fake_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/auth/passkey/risk-stepup/verify",
            "query_string": b"",
            "headers": [
                (b"x-forwarded-for", b"203.0.113.9"),
                (b"user-agent", b"pytest-b59"),
            ],
            "client": ("203.0.113.9", 12345),
        }
    )


def _payload(sub: Subsystem, hub_state: str) -> dict:
    return {
        "flow": "subsystem",
        "hub_state": hub_state,
        "risk_score": 0.72,
        "authreq": {
            "subsystem_id": str(sub.id),
            "client_id": sub.client_id,
            "redirect_uri": (sub.redirect_uris or ["http://localhost:9999/cb"])[0],
            "state": "teststate",
            "code_challenge": "x" * 43,
            "scope": list(sub.scope or ["email", "name"]),
        },
    }


@pytest.fixture
def policy_sub():
    """active subsystem — snapshot + restore policy หลัง test."""
    s = SessionLocal()
    sub = s.query(Subsystem).filter(Subsystem.status == "active").first()
    if not sub:
        s.close()
        pytest.skip("ไม่มี active subsystem")
    snap = (sub.access_policy, sub.access_policy_config)
    sub_id = str(sub.id)
    s.close()
    yield sub_id
    s = SessionLocal()
    sub = s.query(Subsystem).filter(Subsystem.id == sub_id).first()
    sub.access_policy, sub.access_policy_config = snap
    s.commit()
    s.close()


def _fresh_user(db) -> User:
    """user active ที่ **ไม่มี AccessList row** กับ subsystem ใด ๆ (พิสูจน์ policy all)."""
    u = User(
        email=f"b59-{uuid.uuid4().hex[:8]}@uni.ac.th",
        full_name="B59 Tester",
        user_type="student",
        status="active",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _cleanup(db, user_id):
    db.query(AuditLog).filter(AuditLog.actor_id == user_id).delete()
    db.query(LoginSession).filter(LoginSession.user_id == user_id).delete()
    db.query(User).filter(User.id == user_id).delete()
    db.commit()


def test_finalize_allows_policy_all_without_accesslist_row(policy_sub):
    """B59: policy=all + user ไม่มี allow row → finalize ผ่าน (ไม่ 403)."""
    db = SessionLocal()
    user = _fresh_user(db)
    hub_state = f"hs_{uuid.uuid4().hex}"
    try:
        sub = db.query(Subsystem).filter(Subsystem.id == policy_sub).first()
        sub.access_policy = "all"
        sub.access_policy_config = None
        db.commit()

        redis_client.setex(f"authreq:{hub_state}", 300, "1")
        url = _finalize_after_reauth(
            user=user,
            payload=_payload(sub, hub_state),
            request=_fake_request(),
            db=db,
            method="passkey",
        )
        assert (
            isinstance(url, str) and "code=" in url
        ), "policy=all ต้องออก auth code ไม่ใช่ 403"
    finally:
        redis_client.delete(f"authreq:{hub_state}")
        _cleanup(db, user.id)
        db.close()


def test_finalize_still_denies_explicit_not_whitelisted(policy_sub):
    """regression: policy=explicit + user ไม่อยู่ whitelist → ยัง 403 (deny ไม่พัง)."""
    db = SessionLocal()
    user = _fresh_user(db)
    hub_state = f"hs_{uuid.uuid4().hex}"
    try:
        sub = db.query(Subsystem).filter(Subsystem.id == policy_sub).first()
        sub.access_policy = "explicit"
        sub.access_policy_config = None
        db.commit()

        redis_client.setex(f"authreq:{hub_state}", 300, "1")
        with pytest.raises(HTTPException) as ei:
            _finalize_after_reauth(
                user=user,
                payload=_payload(sub, hub_state),
                request=_fake_request(),
                db=db,
                method="passkey",
            )
        assert ei.value.status_code == 403
    finally:
        redis_client.delete(f"authreq:{hub_state}")
        _cleanup(db, user.id)
        db.close()
