"""Tests — "กำลังออนไลน์" ใน /admin/activity ใช้ presence heartbeat (last_seen_at).

บริบทบั๊กเดิม (หน้า activity):
  - online นับจาก created_at อยู่ใน 15 นาที → ปิดแท็บไม่ logout ยังโชว์ online จนครบ
    15 นาที + คน active เกิน 15 นาที (refresh) กลับหาย
  - active_cond กรองแค่ block → session ที่ challenge/mfa แต่ไม่ผ่าน step-up
    (jti IS NULL = ไม่เคยได้ token) ถูกนับเป็น online = ghost

แก้เป็น:
  - online = logout_at NULL + jti NOT NULL + COALESCE(last_seen,created) >= 5 นาที
    + decision ไม่ใช่ block
  - /auth/heartbeat + refresh bump last_seen_at

หมายเหตุ: สร้าง session จริงลง DB (commit) แล้วลบทิ้งใน teardown — ใช้ user ที่ seed ไว้
รัน: docker compose exec hub-backend pytest tests/test_activity_online.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.models import LoginSession
from app.services.jwt_service import create_access_token


@pytest.fixture
def cleanup_sessions(db):
    """เก็บ id ของ session ที่เทสต์สร้าง แล้วลบทิ้งท้ายเทสต์ (แม้ fail)."""
    ids: list = []
    yield ids
    if ids:
        db.query(LoginSession).filter(LoginSession.id.in_(ids)).delete(
            synchronize_session=False
        )
        db.commit()


def _mk_session(db, ids, user, **kw):
    """สร้าง LoginSession + commit + จำ id ไว้ลบ. default = online เต็มเงื่อนไข."""
    now = datetime.utcnow()
    defaults = dict(
        user_id=user.id,
        subsystem_id=None,
        ip="203.0.113.99",
        decision="allow",
        jti="test-jti-" + str(len(ids)),
        created_at=now,
        last_seen_at=now,
        logout_at=None,
        login_method="google",
    )
    defaults.update(kw)
    s = LoginSession(**defaults)
    db.add(s)
    db.commit()
    ids.append(s.id)
    return s


@pytest.fixture
def active_subsystem(db):
    from app.models import Subsystem

    s = db.query(Subsystem).filter(Subsystem.status == "active").first()
    if not s:
        pytest.skip("ไม่มี active subsystem")
    return s


def _active_ids(client, auth_headers, admin_token) -> set:
    r = client.get(
        "/admin/activity?hours=720&limit=200", headers=auth_headers(admin_token)
    )
    assert r.status_code == 200, r.text
    return {it["id"] for it in r.json()["active"]}


# ── เงื่อนไข online ──


def test_fresh_session_is_online(
    client, auth_headers, admin_token, db, cleanup_sessions, student_user
):
    s = _mk_session(db, cleanup_sessions, student_user)
    assert str(s.id) in _active_ids(client, auth_headers, admin_token)


def test_stale_session_not_online(
    client, auth_headers, admin_token, db, cleanup_sessions, student_user
):
    """last_seen เกิน 5 นาที → ไม่ online (คนปิดแท็บไป)."""
    old = datetime.utcnow() - timedelta(minutes=10)
    s = _mk_session(
        db, cleanup_sessions, student_user, last_seen_at=old, created_at=old
    )
    assert str(s.id) not in _active_ids(client, auth_headers, admin_token)


def test_ghost_session_no_jti_not_online(
    client, auth_headers, admin_token, db, cleanup_sessions, student_user
):
    """jti NULL = challenge/mfa ที่ไม่ผ่าน step-up (ไม่เคยได้ token) → ไม่ online."""
    s = _mk_session(db, cleanup_sessions, student_user, jti=None, decision="would_mfa")
    assert str(s.id) not in _active_ids(client, auth_headers, admin_token)


def test_logged_out_session_not_online(
    client, auth_headers, admin_token, db, cleanup_sessions, student_user
):
    s = _mk_session(db, cleanup_sessions, student_user, logout_at=datetime.utcnow())
    assert str(s.id) not in _active_ids(client, auth_headers, admin_token)


def test_blocked_session_not_online(
    client, auth_headers, admin_token, db, cleanup_sessions, student_user
):
    s = _mk_session(db, cleanup_sessions, student_user, decision="block")
    assert str(s.id) not in _active_ids(client, auth_headers, admin_token)


def test_null_last_seen_falls_back_to_created_at(
    client, auth_headers, admin_token, db, cleanup_sessions, student_user
):
    """session เก่าก่อน migration (last_seen NULL) — ใช้ created_at เป็น fallback."""
    s = _mk_session(
        db,
        cleanup_sessions,
        student_user,
        last_seen_at=None,
        created_at=datetime.utcnow(),
    )
    assert str(s.id) in _active_ids(client, auth_headers, admin_token)


def test_active_count_equals_active_len(
    client, auth_headers, admin_token, db, cleanup_sessions, student_user
):
    """KPI active_count ต้อง = จำนวนใน list เสมอ (กันเลขมีแต่ลิสต์ว่าง)."""
    _mk_session(db, cleanup_sessions, student_user)
    r = client.get(
        "/admin/activity?hours=720&limit=200", headers=auth_headers(admin_token)
    )
    body = r.json()
    assert body["active_count"] == len(body["active"])


# ── subsystem = session validity (created_at + TTL 60 นาที) ไม่ใช่ heartbeat ──


def test_subsystem_session_within_ttl_is_active(
    client,
    auth_headers,
    admin_token,
    db,
    cleanup_sessions,
    student_user,
    active_subsystem,
):
    """subsystem: login 30 นาทีก่อน (< 60 TTL) + ไม่ heartbeat → ยัง active (cookie ยัง valid)."""
    t = datetime.utcnow() - timedelta(minutes=30)
    s = _mk_session(
        db,
        cleanup_sessions,
        student_user,
        subsystem_id=active_subsystem.id,
        created_at=t,
        last_seen_at=None,
    )
    assert str(s.id) in _active_ids(client, auth_headers, admin_token)


def test_subsystem_session_past_ttl_not_active(
    client,
    auth_headers,
    admin_token,
    db,
    cleanup_sessions,
    student_user,
    active_subsystem,
):
    """subsystem: login 90 นาทีก่อน (> 60 TTL) → cookie หมดแล้ว → ไม่ active."""
    t = datetime.utcnow() - timedelta(minutes=90)
    s = _mk_session(
        db,
        cleanup_sessions,
        student_user,
        subsystem_id=active_subsystem.id,
        created_at=t,
        last_seen_at=None,
    )
    assert str(s.id) not in _active_ids(client, auth_headers, admin_token)


def test_hub_direct_stale_beyond_5min_but_subsystem_same_age_active(
    client,
    auth_headers,
    admin_token,
    db,
    cleanup_sessions,
    student_user,
    active_subsystem,
):
    """คนละเกณฑ์: อายุ 20 นาทีเท่ากัน — hub-direct หลุด (>5น) แต่ subsystem ยัง (<60น)."""
    t = datetime.utcnow() - timedelta(minutes=20)
    hub = _mk_session(
        db,
        cleanup_sessions,
        student_user,
        subsystem_id=None,
        created_at=t,
        last_seen_at=t,
    )
    sub = _mk_session(
        db,
        cleanup_sessions,
        student_user,
        subsystem_id=active_subsystem.id,
        created_at=t,
        last_seen_at=None,
    )
    active = _active_ids(client, auth_headers, admin_token)
    assert str(hub.id) not in active, "hub-direct 20 นาที ไม่ heartbeat → หลุด"
    assert str(sub.id) in active, "subsystem 20 นาที → ยัง valid (< 60 TTL)"


def test_subsystem_detail_endpoint_uses_same_logic(
    client,
    auth_headers,
    admin_token,
    db,
    cleanup_sessions,
    student_user,
    active_subsystem,
):
    """หน้า subsystem detail (/active-sessions) ต้องใช้เกณฑ์เดียวกับ /activity."""
    t = datetime.utcnow() - timedelta(minutes=30)
    s = _mk_session(
        db,
        cleanup_sessions,
        student_user,
        subsystem_id=active_subsystem.id,
        created_at=t,
        last_seen_at=None,
    )
    r = client.get(
        f"/admin/subsystems/{active_subsystem.id}/active-sessions",
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {x["session_id"] for x in body["sessions"]}
    assert str(s.id) in ids
    # ghost (jti NULL) ต้องไม่โผล่ในหน้านี้ด้วย
    ghost = _mk_session(
        db,
        cleanup_sessions,
        student_user,
        subsystem_id=active_subsystem.id,
        created_at=t,
        last_seen_at=None,
        jti=None,
    )
    r2 = client.get(
        f"/admin/subsystems/{active_subsystem.id}/active-sessions",
        headers=auth_headers(admin_token),
    )
    ids2 = {x["session_id"] for x in r2.json()["sessions"]}
    assert str(ghost.id) not in ids2


# ── heartbeat endpoint ──


def test_heartbeat_bumps_last_seen(client, db, cleanup_sessions, student_user):
    """POST /auth/heartbeat → last_seen_at ของ session ที่มี jti นั้นถูก bump."""
    token, jti = create_access_token(student_user)
    old = datetime.utcnow() - timedelta(minutes=30)
    s = _mk_session(
        db, cleanup_sessions, student_user, jti=jti, last_seen_at=old, created_at=old
    )

    r = client.post("/auth/heartbeat", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["ok"] is True

    db.refresh(s)
    assert s.last_seen_at > old, "last_seen_at ต้องถูก bump เป็นเวลาปัจจุบัน"


def test_heartbeat_bad_token_is_ok_false(client):
    r = client.post("/auth/heartbeat", headers={"Authorization": "Bearer not.a.token"})
    assert r.status_code == 200 and r.json()["ok"] is False
