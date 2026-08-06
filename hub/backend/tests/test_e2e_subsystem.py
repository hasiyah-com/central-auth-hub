"""E2E — ข้อ 2.2 การบริหารจัดการระบบย่อย (ลงทะเบียน/scope/policy/rotate/transfer/สถานะ).

E2E จริงผ่าน HTTP: developer ลงทะเบียนระบบย่อย → รับ client_id + api_key → admin
อนุมัติ (active) → rotate secret → transfer owner. ครอบ positive + negative
(redirect ผิด/scope ผิด/ไม่ใช่ developer/ไม่มี step-up).

รัน: docker compose exec hub-backend pytest tests/test_e2e_subsystem.py -v
"""

from __future__ import annotations

import uuid

import pytest

from app.models import Subsystem, User, SecretRetrievalToken
from app.services.jwt_service import create_access_token
from app.services import stepup_cache
from app.services.secret_service import hash_secret
from app.rate_limiter import limiter


@pytest.fixture(autouse=True)
def _no_rate_limit():
    """ปิด rate limit ระหว่างเทส — เทส register หลายครั้งไม่ให้ติด 5/นาที."""
    prev = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = prev


def _stepup(user):
    token, jti = create_access_token(user)
    stepup_cache.set_granted(str(user.id), jti, method="passkey", ip="127.0.0.1")
    return token


def _make_active_subsystem(db, owner, **over):
    """สร้าง subsystem ตรงใน DB (active, มีเจ้าของ) — สำหรับเทส rotate/transfer
    ที่ต้องการ subsystem อยู่แล้ว (ไม่ได้เทส register endpoint)."""
    sub = Subsystem(
        name=f"e2e-db-{uuid.uuid4().hex[:6]}",
        client_id=f"cli_{uuid.uuid4().hex[:16]}",
        client_secret_hash=hash_secret("dummy-secret-plain"),
        redirect_uris=["https://e2e.example.com/callback"],
        scope=["email", "name"],
        status="active",
        owner_user_id=owner.id,
        access_policy="explicit",
    )
    db.add(sub)
    db.commit()
    return sub


@pytest.fixture
def dev_stepup(teacher_user, auth_headers):
    """teacher (developer) + step-up."""
    return auth_headers(_stepup(teacher_user))


@pytest.fixture
def admin_stepup(admin_user, auth_headers):
    return auth_headers(_stepup(admin_user))


@pytest.fixture
def cleanup_subs(db):
    from app.models import SubsystemChangeRequest, AccessList

    ids = []
    yield ids
    db.rollback()  # เคลียร์ transaction ที่อาจค้างจากเทส
    for sid in ids:
        db.query(SubsystemChangeRequest).filter(
            SubsystemChangeRequest.subsystem_id == sid
        ).delete(synchronize_session=False)
        db.query(SecretRetrievalToken).filter(
            SecretRetrievalToken.subsystem_id == sid
        ).delete(synchronize_session=False)
        db.query(AccessList).filter(AccessList.subsystem_id == sid).delete(
            synchronize_session=False
        )
        db.query(Subsystem).filter(Subsystem.id == sid).delete(
            synchronize_session=False
        )
    db.commit()


def _reg_body(**over):
    body = {
        "name": f"e2e-sub-{uuid.uuid4().hex[:6]}",
        "redirect_uris": ["https://e2e.example.com/callback"],
        "scope": ["email", "name"],
    }
    body.update(over)
    return body


# ═══════════ 2.2(1) ลงทะเบียนระบบย่อย (E2E positive) ═══════════


def test_e2e_register_subsystem_positive(client, dev_stepup, db, cleanup_subs):
    """developer ลงทะเบียน → ได้ client_id + api_key + status pending."""
    r = client.post("/developer/subsystems", headers=dev_stepup, json=_reg_body())
    assert r.status_code in (200, 201), r.text
    body = r.json()
    cleanup_subs.append(body["subsystem_id"])
    assert body["client_id"].startswith("cli_")
    assert body["api_key"]  # roster API key แสดงครั้งเดียว
    assert body["status"] == "pending"
    # ตรวจใน DB: เก็บ secret เป็น hash ไม่ plaintext
    sub = db.query(Subsystem).filter(Subsystem.id == body["subsystem_id"]).first()
    assert sub.client_secret_hash and sub.status == "pending"


def test_e2e_register_then_admin_approve_active(
    client, dev_stepup, admin_stepup, db, cleanup_subs
):
    """ลงทะเบียน (pending) → admin อนุมัติ → active (พร้อมใช้ OAuth)."""
    r = client.post("/developer/subsystems", headers=dev_stepup, json=_reg_body())
    sid = r.json()["subsystem_id"]
    cleanup_subs.append(sid)

    r2 = client.post(f"/admin/subsystems/{sid}/approve", headers=admin_stepup)
    assert r2.status_code == 200, r2.text
    db.expire_all()
    sub = db.query(Subsystem).filter(Subsystem.id == sid).first()
    assert sub.status == "active"


# ═══════════ 2.2(1)/(2) Redirect URI + Data Scope validation (E2E negative) ═══════════


@pytest.mark.parametrize(
    "uri",
    ["javascript:alert(1)", "not-a-url", "ftp://x.com/a", "http://evil.com/cb", ""],
)
def test_e2e_register_bad_redirect_rejected(client, dev_stepup, uri):
    """redirect_uri ผิดปกติ → ถูกปฏิเสธ (422 validation)."""
    r = client.post(
        "/developer/subsystems", headers=dev_stepup, json=_reg_body(redirect_uris=[uri])
    )
    assert r.status_code == 422


@pytest.mark.parametrize("bad_scope", ["national_id", "password", "ssn"])
def test_e2e_register_bad_scope_rejected(client, dev_stepup, bad_scope):
    """scope นอก ALLOWED_SCOPES → 400."""
    r = client.post(
        "/developer/subsystems", headers=dev_stepup, json=_reg_body(scope=[bad_scope])
    )
    assert r.status_code == 400


def test_e2e_register_requires_developer_negative(client, auth_headers, db):
    """student ลงทะเบียนไม่ได้ (require_developer)."""
    student = db.query(User).filter(User.user_type == "student").first()
    token, _ = create_access_token(student)
    r = client.post(
        "/developer/subsystems", headers=auth_headers(token), json=_reg_body()
    )
    assert r.status_code in (401, 403)


def test_e2e_register_requires_stepup_negative(client, auth_headers, teacher_user):
    """ลงทะเบียนโดยไม่มี step-up → 403 (critical action)."""
    token, _ = create_access_token(teacher_user)  # ไม่ grant step-up
    r = client.post(
        "/developer/subsystems", headers=auth_headers(token), json=_reg_body()
    )
    assert r.status_code == 403


# ═══════════ 2.2(6) Rotate secret + Transfer owner (E2E) ═══════════


def test_e2e_rotate_secret_positive(client, dev_stepup, teacher_user, db, cleanup_subs):
    """เจ้าของ rotate secret (ผ่าน step-up) → สร้าง request/ดำเนินการสำเร็จ."""
    sub = _make_active_subsystem(db, teacher_user)
    cleanup_subs.append(sub.id)
    r2 = client.post(
        f"/developer/subsystems/{sub.id}/rotate-secret", headers=dev_stepup
    )
    assert r2.status_code in (200, 201, 202), r2.text


def test_e2e_rotate_secret_requires_stepup_negative(
    client, auth_headers, teacher_user, db, cleanup_subs
):
    """rotate โดยไม่มี step-up → 403."""
    sub = _make_active_subsystem(db, teacher_user)
    cleanup_subs.append(sub.id)
    token, _ = create_access_token(teacher_user)  # no step-up
    r2 = client.post(
        f"/developer/subsystems/{sub.id}/rotate-secret", headers=auth_headers(token)
    )
    assert r2.status_code == 403


def test_e2e_transfer_owner_positive(
    client, dev_stepup, teacher_user, db, cleanup_subs
):
    """โอนสิทธิ์เจ้าของระบบย่อยให้ developer อีกคน (ผ่าน step-up)."""
    sub = _make_active_subsystem(db, teacher_user)
    cleanup_subs.append(sub.id)
    # หา developer อีกคน (ไม่ใช่เจ้าของ)
    target = (
        db.query(User)
        .filter(
            User.user_type.in_(("teacher", "staff")),
            User.status == "active",
            User.email.isnot(None),
            User.id != teacher_user.id,
        )
        .first()
    )
    if not target:
        pytest.skip("ไม่มี developer คนที่สองสำหรับโอนสิทธิ์")
    r2 = client.post(
        f"/developer/subsystems/{sub.id}/transfer-owner",
        headers=dev_stepup,
        json={"new_owner_email": target.email},
    )
    assert r2.status_code == 200, r2.text
    db.expire_all()
    sub2 = db.query(Subsystem).filter(Subsystem.id == sub.id).first()
    assert str(sub2.owner_user_id) == str(target.id)


# ═══════════ 2.2(7) สถิติระบบย่อย (E2E) ═══════════


def test_e2e_subsystem_stats_positive(client, admin_stepup, db):
    """admin ดูสถิติระบบย่อย (จำนวนผู้ใช้/login/สถานะ)."""
    sub = db.query(Subsystem).filter(Subsystem.status == "active").first()
    r = client.get(f"/admin/subsystems/{sub.id}/stats", headers=admin_stepup)
    assert r.status_code == 200 and isinstance(r.json(), dict)


def test_e2e_stats_requires_admin_negative(client, auth_headers, staff_token, db):
    """staff (ไม่ใช่ admin) ดูสถิติไม่ได้."""
    sub = db.query(Subsystem).filter(Subsystem.status == "active").first()
    r = client.get(
        f"/admin/subsystems/{sub.id}/stats", headers=auth_headers(staff_token)
    )
    assert r.status_code == 403
