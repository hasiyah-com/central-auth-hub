"""User Lifecycle Management — Graduated/Resigned statuses (2026-07-06).

ครอบ:
  - _VALID_STATUS / _CASCADE_STATUSES มี graduated/resigned
  - PATCH status → graduated/resigned = cascade revoke เหมือน delete_user
    (revoke AccessList + kick LoginSession + revoke jti + audit log มี
    subsystems_kicked)
  - Reactivate (graduated/resigned → active) restore AccessList ที่ถูก kick ไป
  - เปลี่ยนระหว่าง cascade-status สองตัว (graduated → resigned) ไม่ double-cascade
    ซ้ำ (AccessList ที่ถูก revoke ไปแล้วไม่ถูกแตะอีกรอบ)
  - self-lockout กันไม่ให้ admin ปิดบัญชีตัวเอง (รวม graduated/resigned)
  - get_current_user บล็อก login ด้วยข้อความเฉพาะ status (จบการศึกษา/ลาออก)

รัน:
  docker compose exec hub-backend pytest tests/test_user_lifecycle.py -v
"""

from __future__ import annotations

import uuid

import pytest

from app.deps import _status_block_message
from app.models import AccessList, LoginSession, Subsystem
from app.routers.users import _CASCADE_STATUSES, _VALID_STATUS
from app.services import stepup_cache
from app.services.jwt_service import create_access_token


def _admin_token_with_stepup(admin_user) -> str:
    """ออก JWT ให้ admin + grant step-up สำหรับ jti นั้น → ผ่าน critical-action gate."""
    token, jti = create_access_token(admin_user)
    stepup_cache.set_granted(str(admin_user.id), jti, method="passkey", ip="127.0.0.1")
    return token


@pytest.fixture
def target_with_access(db, student_user):
    """student_user + subsystem + active AccessList + active LoginSession (jti).

    Teardown: ลบ subsystem/access/session ที่สร้างไว้ทดสอบ + คืน status เดิม
    (กัน pollute live dev DB ตาม convention).
    """
    sub = Subsystem(
        name=f"lifecycle-test-{uuid.uuid4().hex[:6]}",
        client_id=f"cli_{uuid.uuid4().hex[:8]}",
        client_secret_hash="x",
        redirect_uris=["http://localhost/cb"],
        scope=["email"],
        status="active",
    )
    db.add(sub)
    db.flush()

    access = AccessList(
        subsystem_id=sub.id, user_id=student_user.id, entry_type="allow"
    )
    db.add(access)

    _, jti = create_access_token(student_user)
    sess = LoginSession(
        user_id=student_user.id,
        subsystem_id=sub.id,
        ip="127.0.0.1",
        user_agent="pytest",
        login_method="google",
        decision="allow",
        jti=jti,
    )
    db.add(sess)
    db.commit()
    db.refresh(access)
    db.refresh(sess)

    original_status = student_user.status

    yield student_user, sub, access, sess

    db.query(LoginSession).filter(LoginSession.id == sess.id).delete()
    db.query(AccessList).filter(AccessList.id == access.id).delete()
    db.query(Subsystem).filter(Subsystem.id == sub.id).delete()
    student_user.status = original_status
    db.commit()


# ─────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_valid_status_includes_graduated_resigned():
    assert {"graduated", "resigned"} <= _VALID_STATUS


@pytest.mark.smoke
def test_cascade_statuses_are_deleted_graduated_resigned():
    assert _CASCADE_STATUSES == {"deleted", "graduated", "resigned"}


# ─────────────────────────────────────────────────────────────
# Cascade revoke on status change (via PATCH, not just DELETE endpoint)
# ─────────────────────────────────────────────────────────────


def test_status_change_to_graduated_cascades_revoke(
    client, db, admin_user, target_with_access, auth_headers
):
    user, sub, access, sess = target_with_access
    token = _admin_token_with_stepup(admin_user)

    r = client.patch(
        f"/admin/users/{user.id}",
        headers=auth_headers(token),
        json={"status": "graduated"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "graduated"

    db.refresh(access)
    db.refresh(sess)
    assert access.revoked_at is not None
    assert sess.logout_at is not None


def test_status_change_to_resigned_cascades_revoke(
    client, db, admin_user, target_with_access, auth_headers
):
    user, sub, access, sess = target_with_access
    token = _admin_token_with_stepup(admin_user)

    r = client.patch(
        f"/admin/users/{user.id}",
        headers=auth_headers(token),
        json={"status": "resigned"},
    )
    assert r.status_code == 200

    db.refresh(access)
    db.refresh(sess)
    assert access.revoked_at is not None
    assert sess.logout_at is not None


def test_status_change_audit_log_records_subsystems_kicked(
    client, db, admin_user, target_with_access, auth_headers
):
    from app.models import AuditLog

    user, sub, access, sess = target_with_access
    token = _admin_token_with_stepup(admin_user)

    r = client.patch(
        f"/admin/users/{user.id}",
        headers=auth_headers(token),
        json={"status": "graduated"},
    )
    assert r.status_code == 200

    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "update_user", AuditLog.target_id == user.id)
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert log is not None
    assert log.metadata_json["cascade_exit"] is True
    kicked_ids = [s["subsystem_id"] for s in log.metadata_json["subsystems_kicked"]]
    assert str(sub.id) in kicked_ids


# ─────────────────────────────────────────────────────────────
# Reactivation restores access
# ─────────────────────────────────────────────────────────────


def test_reactivate_from_graduated_restores_access(
    client, db, admin_user, target_with_access, auth_headers
):
    user, sub, access, sess = target_with_access
    token = _admin_token_with_stepup(admin_user)

    r1 = client.patch(
        f"/admin/users/{user.id}",
        headers=auth_headers(token),
        json={"status": "graduated"},
    )
    assert r1.status_code == 200
    db.refresh(access)
    assert access.revoked_at is not None

    r2 = client.patch(
        f"/admin/users/{user.id}",
        headers=auth_headers(token),
        json={"status": "active"},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "active"

    db.refresh(access)
    assert access.revoked_at is None


def test_reactivate_from_resigned_restores_access(
    client, db, admin_user, target_with_access, auth_headers
):
    user, sub, access, sess = target_with_access
    token = _admin_token_with_stepup(admin_user)

    client.patch(
        f"/admin/users/{user.id}",
        headers=auth_headers(token),
        json={"status": "resigned"},
    )
    db.refresh(access)
    assert access.revoked_at is not None

    r = client.patch(
        f"/admin/users/{user.id}",
        headers=auth_headers(token),
        json={"status": "active"},
    )
    assert r.status_code == 200
    db.refresh(access)
    assert access.revoked_at is None


def test_transition_between_cascade_statuses_no_double_kick(
    client, db, admin_user, target_with_access, auth_headers
):
    """graduated → resigned (สองสถานะ cascade ต่อกัน) ไม่ควร re-run cascade ซ้ำ
    (AccessList ที่ revoked_at ตั้งไว้แล้วไม่ถูกแตะ/เปลี่ยนเวลาอีกรอบ)."""
    user, sub, access, sess = target_with_access
    token = _admin_token_with_stepup(admin_user)

    client.patch(
        f"/admin/users/{user.id}",
        headers=auth_headers(token),
        json={"status": "graduated"},
    )
    db.refresh(access)
    first_revoked_at = access.revoked_at
    assert first_revoked_at is not None

    r = client.patch(
        f"/admin/users/{user.id}",
        headers=auth_headers(token),
        json={"status": "resigned"},
    )
    assert r.status_code == 200

    db.refresh(access)
    assert access.revoked_at == first_revoked_at  # ไม่ถูก re-cascade


# ─────────────────────────────────────────────────────────────
# Self-lockout guard
# ─────────────────────────────────────────────────────────────


def test_admin_cannot_set_own_status_to_graduated(client, admin_user, auth_headers):
    token = _admin_token_with_stepup(admin_user)
    r = client.patch(
        f"/admin/users/{admin_user.id}",
        headers=auth_headers(token),
        json={"status": "graduated"},
    )
    assert r.status_code == 400


def test_admin_cannot_set_own_status_to_resigned(client, admin_user, auth_headers):
    token = _admin_token_with_stepup(admin_user)
    r = client.patch(
        f"/admin/users/{admin_user.id}",
        headers=auth_headers(token),
        json={"status": "resigned"},
    )
    assert r.status_code == 400


# ─────────────────────────────────────────────────────────────
# Login-block message per status
# ─────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_status_block_message_graduated():
    msg = _status_block_message("graduated")
    assert "จบการศึกษา" in msg


@pytest.mark.smoke
def test_status_block_message_resigned():
    msg = _status_block_message("resigned")
    assert "ลาออก" in msg


@pytest.mark.smoke
def test_status_block_message_unknown_falls_back():
    msg = _status_block_message("weird_status")
    assert "weird_status" in msg
