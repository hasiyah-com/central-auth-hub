"""Integration test — Access Policy enforcement ที่ login finalizer จริง.

เรียก oauth._finalize_subsystem_login ตรง ๆ (login path จริง ลบแค่ Google OAuth)
→ พิสูจน์ว่า policy ถูก enforce ตอน login (ไม่ใช่แค่ engine unit).

เน้น deny path (deterministic, ไม่พึ่ง ML/RBA — policy check เป็นด่านแรก raise 403).
allow path ครอบด้วย test_access_policy (engine) + explicit เดิมที่ทำงานอยู่.

รัน: docker compose exec hub-backend pytest tests/test_oauth_policy_integration.py -v
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.database import SessionLocal
from app.models import Subsystem, User
from app.routers.oauth import _finalize_subsystem_login


def _fake_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/oauth/callback",
            "query_string": b"",
            "headers": [
                (b"x-forwarded-for", b"203.0.113.9"),
                (b"user-agent", b"pytest-integration"),
            ],
            "client": ("203.0.113.9", 12345),
        }
    )


def _authreq(sub: Subsystem) -> dict:
    return {
        "subsystem_id": str(sub.id),
        "client_id": sub.client_id,
        "redirect_uri": (sub.redirect_uris or ["http://localhost:9999/cb"])[0],
        "state": "teststate",
        "code_challenge": "x" * 43,
        "scope": list(sub.scope or ["email", "name"]),
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


@pytest.mark.asyncio
async def test_finalize_denies_role_policy(policy_sub):
    """student เข้า subsystem ที่ policy=role(teacher) → 403 ที่ login finalizer."""
    db = SessionLocal()
    try:
        sub = db.query(Subsystem).filter(Subsystem.id == policy_sub).first()
        sub.access_policy = "role"
        sub.access_policy_config = {"roles": ["teacher"]}
        db.commit()

        student = (
            db.query(User)
            .filter(User.user_type == "student", User.status == "active")
            .first()
        )
        if not student:
            pytest.skip("ไม่มี student")

        with pytest.raises(HTTPException) as ei:
            await _finalize_subsystem_login(
                user=student,
                authreq=_authreq(sub),
                hub_state="hs_test_deny",
                request=_fake_request(),
                db=db,
                provider="google",
            )
        assert ei.value.status_code == 403
    finally:
        db.rollback()
        db.close()


@pytest.mark.asyncio
async def test_finalize_denies_when_inactive_user(policy_sub):
    """policy=all แต่ user suspended → 403 (active check)."""
    db = SessionLocal()
    try:
        sub = db.query(Subsystem).filter(Subsystem.id == policy_sub).first()
        sub.access_policy = "all"
        sub.access_policy_config = None
        db.commit()

        u = (
            db.query(User)
            .filter(User.user_type == "student", User.status == "active")
            .first()
        )
        if not u:
            pytest.skip("ไม่มี student")
        u.status = "suspended"
        db.flush()

        with pytest.raises(HTTPException) as ei:
            await _finalize_subsystem_login(
                user=u,
                authreq=_authreq(sub),
                hub_state="hs_test_inactive",
                request=_fake_request(),
                db=db,
                provider="google",
            )
        assert ei.value.status_code == 403
    finally:
        db.rollback()  # คืน user.status + policy
        db.close()
