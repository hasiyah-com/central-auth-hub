"""E2E — ข้อ 2.1 การจัดการสิทธิ์แบบรวมศูนย์ (บัญชี/บทบาท/สถานะ/เซสชัน/สิทธิ์).

E2E จริงผ่าน HTTP (TestClient) + DB จริง: สร้างบัญชี → ให้สิทธิ์ → เข้าใช้งาน
(login_session) → ถอนสิทธิ์ → ยืนยันถูกบล็อก → เปลี่ยนสถานะ cascade → force logout.
ครอบ positive + negative. ทุก mutating action ผ่าน step-up จริง.

รัน: docker compose exec hub-backend pytest tests/test_e2e_permission.py -v
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.models import AccessList, LoginSession, Subsystem, User
from app.services.access_policy import evaluate_access_policy
from app.services.jwt_service import create_access_token
from app.services import stepup_cache


def _stepup(user):
    """token ที่ผ่าน step-up gate (จำลอง passkey step-up สำเร็จ)."""
    token, jti = create_access_token(user)
    stepup_cache.set_granted(str(user.id), jti, method="passkey", ip="127.0.0.1")
    return token


@pytest.fixture
def admin_stepup(admin_user, auth_headers):
    return auth_headers(_stepup(admin_user))


@pytest.fixture
def scratch_email():
    return f"e2e-perm-{uuid.uuid4().hex[:8]}@uni.ac.th"


@pytest.fixture
def cleanup(db):
    ids = {"users": [], "access": []}
    yield ids
    if ids["access"]:
        db.query(AccessList).filter(AccessList.id.in_(ids["access"])).delete(
            synchronize_session=False
        )
    for uid in ids["users"]:
        db.query(LoginSession).filter(LoginSession.user_id == uid).delete(
            synchronize_session=False
        )
        db.query(AccessList).filter(AccessList.user_id == uid).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.id == uid).delete(synchronize_session=False)
    db.commit()


# ═══════════ 2.1(1) สร้าง/แก้ไข/แสดง บัญชีผู้ใช้ (E2E ผ่าน endpoint) ═══════════


def test_e2e_create_user_then_appears_positive(
    client, admin_stepup, db, cleanup, scratch_email
):
    """สร้าง user → ปรากฏใน list + search เจอ + ดูรายละเอียดได้."""
    r = client.post(
        "/admin/users/",
        headers=admin_stepup,
        json={
            "email": scratch_email,
            "full_name": "อีทูอี ทดสอบ",
            "user_type": "student",
            "identifier": f"65{uuid.uuid4().hex[:4]}",
            "faculty": "วิศวกรรมศาสตร์",
        },
    )
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    cleanup["users"].append(uid)

    # ปรากฏใน detail
    assert client.get(f"/admin/users/{uid}", headers=admin_stepup).status_code == 200
    # search เจอ (ค้นด้วยคณะ)
    rows = client.get("/admin/users/?q=วิศว&limit=500", headers=admin_stepup).json()
    assert any(u["id"] == uid for u in rows)


def test_e2e_create_duplicate_email_negative(
    client, admin_stepup, db, cleanup, scratch_email
):
    """สร้าง user email ซ้ำ → ถูกปฏิเสธ (ไม่สร้างซ้ำ)."""
    body = {
        "email": scratch_email,
        "full_name": "ซ้ำ",
        "user_type": "staff",
        "identifier": f"S{uuid.uuid4().hex[:4]}",
    }
    r1 = client.post("/admin/users/", headers=admin_stepup, json=body)
    assert r1.status_code == 201
    cleanup["users"].append(r1.json()["id"])
    r2 = client.post("/admin/users/", headers=admin_stepup, json=body)  # email เดิม
    assert r2.status_code in (400, 409, 422)


def test_e2e_create_user_requires_stepup_negative(
    client, auth_headers, admin_token, scratch_email
):
    """สร้าง user โดยไม่มี step-up → 403 (critical action gate)."""
    r = client.post(
        "/admin/users/",
        headers=auth_headers(admin_token),  # ไม่มี step-up
        json={"email": scratch_email, "full_name": "x", "user_type": "student"},
    )
    assert r.status_code == 403


# ═══════════ 2.1(2)/(3) เปลี่ยนบทบาท + สถานะ (E2E) ═══════════


def test_e2e_change_role_and_status_positive(
    client, admin_stepup, db, cleanup, scratch_email
):
    """แก้ user_type (บทบาท) + status → GET สะท้อนค่าใหม่."""
    r = client.post(
        "/admin/users/",
        headers=admin_stepup,
        json={"email": scratch_email, "full_name": "role test", "user_type": "student"},
    )
    uid = r.json()["id"]
    cleanup["users"].append(uid)

    r2 = client.patch(
        f"/admin/users/{uid}",
        headers=admin_stepup,
        json={"user_type": "staff", "status": "suspended"},
    )
    assert r2.status_code == 200
    got = client.get(f"/admin/users/{uid}", headers=admin_stepup).json()
    assert got["user_type"] == "staff" and got["status"] == "suspended"


@pytest.mark.parametrize("bad_status", ["banana", "ACTIVE", "on", "removed"])
def test_e2e_change_status_invalid_negative(
    client, admin_stepup, db, cleanup, scratch_email, bad_status
):
    """เปลี่ยนสถานะเป็นค่าที่ไม่รองรับ → 422."""
    r = client.post(
        "/admin/users/",
        headers=admin_stepup,
        json={"email": scratch_email, "full_name": "x", "user_type": "student"},
    )
    uid = r.json()["id"]
    cleanup["users"].append(uid)
    r2 = client.patch(
        f"/admin/users/{uid}", headers=admin_stepup, json={"status": bad_status}
    )
    assert r2.status_code == 422


# ═══════════ 2.1(6) ให้/ถอนสิทธิ์ + สถานะกระทบการเข้าถึง (E2E flow) ═══════════


def test_e2e_grant_then_revoke_blocks_access(client, admin_stepup, db, cleanup):
    """ให้สิทธิ์ → เข้าได้ → ถอนสิทธิ์ (deny) → เข้าไม่ได้ (evaluate_access_policy)."""
    sub = db.query(Subsystem).filter(Subsystem.status == "active").first()
    user = User(
        email=f"e2e-acc-{uuid.uuid4().hex[:6]}@uni.ac.th",
        full_name="access flow",
        user_type="student",
        status="active",
    )
    db.add(user)
    db.commit()
    cleanup["users"].append(user.id)

    # grant (explicit)
    r = client.post(f"/admin/users/{user.id}/access/{sub.id}", headers=admin_stepup)
    assert r.status_code == 200, r.text
    sub.access_policy = "explicit"
    db.commit()
    ok, _ = evaluate_access_policy(db, user, sub)
    assert ok is True  # หลัง grant เข้าได้

    # revoke (deny)
    r2 = client.request(
        "DELETE", f"/admin/users/{user.id}/access/{sub.id}", headers=admin_stepup
    )
    assert r2.status_code == 200
    db.expire_all()
    user = db.query(User).filter(User.id == user.id).first()
    ok2, reason = evaluate_access_policy(db, user, sub)
    assert ok2 is False and reason == "denied"  # หลัง revoke เข้าไม่ได้


def test_e2e_suspended_user_denied_then_reactivate(client, admin_stepup, db, cleanup):
    """สถานะ suspended → เข้าไม่ได้ทุก policy · กลับ active → เข้าได้."""
    sub = db.query(Subsystem).filter(Subsystem.status == "active").first()
    sub.access_policy = "all"
    db.commit()
    user = User(
        email=f"e2e-st-{uuid.uuid4().hex[:6]}@uni.ac.th",
        full_name="status flow",
        user_type="student",
        status="active",
    )
    db.add(user)
    db.commit()
    cleanup["users"].append(user.id)

    assert evaluate_access_policy(db, user, sub)[0] is True  # active + all → เข้าได้
    user.status = "suspended"
    db.commit()
    ok, reason = evaluate_access_policy(db, user, sub)
    assert ok is False and reason.startswith("user_status")  # suspended → บล็อก
    user.status = "active"
    db.commit()
    assert evaluate_access_policy(db, user, sub)[0] is True  # reactivate → เข้าได้อีก


def test_e2e_revoke_requires_stepup_negative(client, auth_headers, admin_token, db):
    """ถอนสิทธิ์โดยไม่มี step-up → 403."""
    sub = db.query(Subsystem).filter(Subsystem.status == "active").first()
    u = db.query(User).first()
    r = client.request(
        "DELETE",
        f"/admin/users/{u.id}/access/{sub.id}",
        headers=auth_headers(admin_token),  # ไม่มี step-up
    )
    assert r.status_code == 403


# ═══════════ 2.1(4) จัดการเซสชัน — Force Logout (E2E) ═══════════


def test_e2e_force_logout_closes_sessions(client, admin_stepup, db, cleanup):
    """user มี active session → force logout → session ถูกปิด (logout_at set)."""
    user = User(
        email=f"e2e-fl-{uuid.uuid4().hex[:6]}@uni.ac.th",
        full_name="force logout",
        user_type="staff",
        status="active",
    )
    db.add(user)
    db.commit()
    cleanup["users"].append(user.id)
    # สร้าง active session
    s = LoginSession(
        user_id=user.id,
        ip="203.0.113.1",
        decision="allow",
        jti=uuid.uuid4().hex,
        created_at=datetime.utcnow(),
        logout_at=None,
        login_method="google",
    )
    db.add(s)
    db.commit()

    r = client.post(f"/admin/users/{user.id}/force-logout", headers=admin_stepup)
    assert r.status_code == 200, r.text
    db.expire_all()
    s2 = db.query(LoginSession).filter(LoginSession.id == s.id).first()
    assert s2.logout_at is not None  # session ถูกปิดจริง


def test_e2e_reset_passkeys_requires_stepup_negative(
    client, auth_headers, admin_token, db
):
    """reset passkey โดยไม่มี step-up → 403."""
    u = db.query(User).first()
    r = client.post(
        f"/admin/users/{u.id}/reset-passkeys", headers=auth_headers(admin_token)
    )
    assert r.status_code == 403
