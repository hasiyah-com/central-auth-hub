"""Security test — students must not get a Hub-direct JWT via passkey login (audit run-2 #3).

B19: students are blocked at Hub-direct login (Google/LINE callbacks) and may enter only
through subsystems. Students CAN enroll a passkey (for subsystem risk-stepup), but passkey
login_finish / login_discoverable_finish must NOT mint a hub.internal JWT for them.

We monkeypatch webauthn_service.auth_complete/discoverable_complete (a real assertion needs a
mock authenticator) to return a result for a student user, and assert the endpoint returns 403
before any token is issued.

รัน:
    docker compose exec hub-backend pytest tests/test_passkey_student_block.py -v
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.routers.passkey as pk
from app.models import AuditLog, User


@pytest.fixture
def student(db):
    u = User(
        email=f"stud-{uuid.uuid4().hex[:8]}@uni.ac.th",
        full_name="Student Tester",
        user_type="student",
        identifier=f"65{uuid.uuid4().hex[:4]}",
        status="active",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    uid = u.id
    yield u
    db.query(AuditLog).filter(AuditLog.actor_id == uid).delete(
        synchronize_session=False
    )
    db.query(User).filter(User.id == uid).delete(synchronize_session=False)
    db.commit()


# ── unit: the guard helper ──────────────────────────────────────────────────


def test_helper_blocks_student(student, db):
    with pytest.raises(HTTPException) as exc:
        pk._block_student_hub_login(student, db, "127.0.0.1", "passkey")
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "student_blocked"


def test_helper_allows_non_student(db, admin_user):
    # staff/teacher/admin → no raise
    assert pk._block_student_hub_login(admin_user, db, "127.0.0.1", "passkey") is None


# ── endpoint: passkey login_finish rejects a student (mocked assertion) ──────


def _fake_result(user):
    return SimpleNamespace(
        user=user,
        counter_regression=False,
        credential=SimpleNamespace(id=uuid.uuid4(), sign_count=1),
        previous_sign_count=0,
    )


def test_login_finish_blocks_student(client, db, student, monkeypatch):
    monkeypatch.setattr(
        pk.webauthn_service,
        "auth_complete",
        lambda email, credential, db, ip=None, user_agent=None: _fake_result(student),
    )
    r = client.post(
        "/auth/passkey/login/finish",
        json={"email": student.email, "credential": {"rawId": "AAAA"}},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "student_blocked"
    # audit trail recorded
    db.expire_all()
    logged = (
        db.query(AuditLog)
        .filter(
            AuditLog.actor_id == student.id,
            AuditLog.action == "hub_login_blocked_student",
        )
        .first()
    )
    assert logged is not None


def test_login_discoverable_finish_blocks_student(client, db, student, monkeypatch):
    monkeypatch.setattr(
        pk.webauthn_service,
        "discoverable_complete",
        lambda credential, db, ip=None, user_agent=None: _fake_result(student),
    )
    r = client.post(
        "/auth/passkey/login/discoverable/finish",
        json={"credential": {"rawId": "AAAA"}},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "student_blocked"
