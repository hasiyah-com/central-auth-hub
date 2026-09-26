"""step-up OTP ทาง email ที่ไม่ผ่านต้องมี audit event และถูกนับใน failed_logins_24h.

นับเฉพาะ otp_invalid (ตรวจ OTP แล้วผิดจริง):
  - otp_locked  — ปฏิเสธจากสถานะล็อกก่อนตรวจ OTP ใหม่ · นับซ้ำจะเพิ่มความล้มเหลวซ้ำจากสถานะเดิม
  - otp_expired — ไม่มี OTP ให้ตรวจ ไม่ใช่การเดาผิด
"""

import json
import uuid
from datetime import datetime

import pytest

from app.models import AuditLog, LoginSession, User
from app.rate_limiter import limiter
from app.redis_client import redis_client
from app.security.rule_engine import FEAT
from app.services import mfa_service
from app.services.feature_extraction import extract_session_features
from app.services.jwt_service import create_access_token

VERIFY = "/auth/stepup/otp/verify"
KEY = "stepup:otp:{}"


@pytest.fixture(autouse=True)
def _no_rate_limit():
    prev = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = prev


@pytest.fixture
def user(db):
    u = User(
        email=f"otpfail-{uuid.uuid4().hex[:8]}@uni.ac.th",
        full_name="OTP Failure Tester",
        user_type="staff",
        identifier=f"S{uuid.uuid4().hex[:4]}",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    yield u
    redis_client.delete(KEY.format(u.id))
    db.query(AuditLog).filter(AuditLog.actor_id == u.id).delete(
        synchronize_session=False
    )
    db.query(LoginSession).filter(LoginSession.user_id == u.id).delete()
    db.delete(u)
    db.commit()


def _headers(user, auth_headers):
    token, _ = create_access_token(user)
    return auth_headers(token)


def _seed_otp(user, otp="123456", attempts=0):
    redis_client.setex(
        KEY.format(user.id),
        300,
        json.dumps({"hash": mfa_service.hash_otp(otp), "attempts": attempts}),
    )


def _failed_rows(db, user):
    db.expire_all()
    return (
        db.query(AuditLog)
        .filter(AuditLog.actor_id == user.id, AuditLog.action == "stepup_otp_failed")
        .all()
    )


def test_invalid_otp_is_audited_and_counted(client, db, user, auth_headers):
    _seed_otp(user)
    headers = {**_headers(user, auth_headers), "X-Forwarded-For": "203.0.113.9"}
    r = client.post(VERIFY, json={"otp": "000000"}, headers=headers)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "otp_invalid"

    rows = _failed_rows(db, user)
    assert len(rows) == 1
    assert rows[0].target_id == user.id
    assert rows[0].metadata_json.get("code") == "otp_invalid"
    assert str(rows[0].ip) == "203.0.113.9"

    feats = extract_session_features(
        db, user.id, "1.2.3.4", "Mozilla/5.0", "TH", now=datetime.utcnow()
    )
    assert feats[FEAT["failed_logins_24h"]] == 1.0


def test_invalid_otp_still_increments_attempts(client, db, user, auth_headers):
    _seed_otp(user, attempts=2)
    client.post(VERIFY, json={"otp": "000000"}, headers=_headers(user, auth_headers))
    data = json.loads(redis_client.get(KEY.format(user.id)))
    assert data["attempts"] == 3


def test_locked_state_is_not_counted(client, db, user, auth_headers):
    _seed_otp(user, attempts=5)
    r = client.post(
        VERIFY, json={"otp": "000000"}, headers=_headers(user, auth_headers)
    )
    assert r.json()["detail"]["code"] == "otp_locked"
    assert _failed_rows(db, user) == []


def test_expired_otp_is_not_counted(client, db, user, auth_headers):
    r = client.post(
        VERIFY, json={"otp": "000000"}, headers=_headers(user, auth_headers)
    )
    assert r.json()["detail"]["code"] == "otp_expired"
    assert _failed_rows(db, user) == []
