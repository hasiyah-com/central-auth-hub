"""Tests — Developer portal subsystem insights (owner-scoped KPI/health/sessions/audit).

หน้า developer portal detail ต้องแสดงข้อมูลชุดเดียวกับหน้า admin
(`/admin/subsystems/{id}/...`) แต่ scope เฉพาะ subsystem ที่ตัวเองเป็นเจ้าของ:
  GET /developer/subsystems/{id}/stats            KPI 7 วัน + daily logins
  GET /developer/subsystems/{id}/health-history   latency ย้อนหลัง
  GET /developer/subsystems/{id}/active-sessions  session ที่ยัง valid (read-only)
  GET /developer/subsystems/{id}/audit            audit trail ของ subsystem

ครอบ security ที่สำคัญ:
  - owner เห็นข้อมูลของตัวเอง (200)
  - developer คนอื่นที่ไม่ใช่เจ้าของ → 404 (owner-scoped, กัน IDOR — B1/B19)
  - hub admin override ได้ (200)
  - student ถูกบล็อกที่ require_developer (403)
  - ไม่มี endpoint revoke ฝั่ง developer (read-only จริง)

logic ใช้ร่วมกับ admin ผ่าน app.services.subsystem_insights.
รัน: bash scripts/test/run_tests.sh tests/test_developer_subsystem_insights.py
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from app.models import AuditLog, LoginSession, Subsystem
from app.services.secret_service import hash_secret


@pytest.fixture
def owned_sub(db, teacher_user):
    """subsystem ที่ teacher_user เป็นเจ้าของ + login session + audit log — ลบทิ้งท้ายเทสต์."""
    sub = Subsystem(
        name=f"insight-{uuid.uuid4().hex[:6]}",
        client_id=f"cli_{uuid.uuid4().hex[:10]}",
        client_secret_hash=hash_secret("x"),
        redirect_uris=["https://sub.example.com/cb"],
        scope=["email"],
        status="active",
        owner_user_id=teacher_user.id,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)

    now = datetime.utcnow()
    sess = LoginSession(
        user_id=teacher_user.id,
        subsystem_id=sub.id,
        ip="203.0.113.10",
        decision="allow",
        jti=f"test-jti-{uuid.uuid4().hex[:8]}",
        created_at=now,
        last_seen_at=now,
        logout_at=None,
        login_method="google",
    )
    db.add(sess)
    audit = AuditLog(
        actor_id=teacher_user.id,
        action="subsystem_insight_probe",
        target_type="subsystem",
        target_id=sub.id,
        ip="203.0.113.10",
        metadata_json={"note": "test"},
    )
    db.add(audit)
    db.commit()

    yield {"sub": sub, "session": sess, "audit": audit}

    db.query(LoginSession).filter(LoginSession.subsystem_id == sub.id).delete(
        synchronize_session=False
    )
    db.query(AuditLog).filter(
        AuditLog.target_type == "subsystem", AuditLog.target_id == sub.id
    ).delete(synchronize_session=False)
    db.query(Subsystem).filter(Subsystem.id == sub.id).delete(synchronize_session=False)
    db.commit()


# ── owner เห็นข้อมูลของตัวเอง ─────────────────────────────


def test_stats_owner_ok(client, auth_headers, teacher_token, owned_sub):
    sid = owned_sub["sub"].id
    r = client.get(
        f"/developer/subsystems/{sid}/stats?days=7", headers=auth_headers(teacher_token)
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_logins"] >= 1
    assert data["unique_users"] >= 1
    assert data["active_now"] >= 1  # session สดที่ fixture สร้าง
    assert isinstance(data["daily"], list)
    assert data["subsystem"]["id"] == str(sid)


def test_health_history_owner_ok(client, auth_headers, teacher_token, owned_sub):
    sid = owned_sub["sub"].id
    r = client.get(
        f"/developer/subsystems/{sid}/health-history",
        headers=auth_headers(teacher_token),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    # ยังไม่เคย ping / Redis ว่าง → points ว่าง (fail-safe) แต่ต้องมี key ครบ
    assert isinstance(data["points"], list)
    assert "avg_latency_ms" in data
    assert data["interval_sec"] == 300


def test_active_sessions_owner_ok(client, auth_headers, teacher_token, owned_sub):
    sid = owned_sub["sub"].id
    r = client.get(
        f"/developer/subsystems/{sid}/active-sessions",
        headers=auth_headers(teacher_token),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] >= 1
    ids = {s["session_id"] for s in data["sessions"]}
    assert str(owned_sub["session"].id) in ids


def test_audit_owner_ok(client, auth_headers, teacher_token, owned_sub):
    sid = owned_sub["sub"].id
    r = client.get(
        f"/developer/subsystems/{sid}/audit", headers=auth_headers(teacher_token)
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] >= 1
    actions = {it["action"] for it in data["items"]}
    assert "subsystem_insight_probe" in actions


# ── owner-scoping / RBAC ─────────────────────────────────


def test_non_owner_developer_404(client, auth_headers, staff_token, owned_sub):
    """developer คนอื่น (staff, ไม่ใช่เจ้าของ) → 404 owner-scoped (กัน IDOR)."""
    sid = owned_sub["sub"].id
    r = client.get(
        f"/developer/subsystems/{sid}/stats", headers=auth_headers(staff_token)
    )
    assert r.status_code == 404, r.text


def test_admin_override_ok(client, auth_headers, admin_token, owned_sub):
    """hub admin = supervisor → เข้าดูข้อมูลของ subsystem ใครก็ได้."""
    sid = owned_sub["sub"].id
    r = client.get(
        f"/developer/subsystems/{sid}/stats", headers=auth_headers(admin_token)
    )
    assert r.status_code == 200, r.text


def test_student_forbidden(client, auth_headers, student_token, owned_sub):
    """student ถูกบล็อกที่ require_developer (ไม่ใช่ owner check) → 403."""
    sid = owned_sub["sub"].id
    r = client.get(
        f"/developer/subsystems/{sid}/stats", headers=auth_headers(student_token)
    )
    assert r.status_code == 403, r.text


def test_no_developer_revoke_endpoint(client, auth_headers, teacher_token, owned_sub):
    """read-only จริง — developer ไม่มี endpoint revoke session (revoke = admin เท่านั้น)."""
    sid = owned_sub["sub"].id
    ssid = owned_sub["session"].id
    r = client.post(
        f"/developer/subsystems/{sid}/sessions/{ssid}/revoke?level=notify",
        headers=auth_headers(teacher_token),
    )
    assert r.status_code in (404, 405), r.text
