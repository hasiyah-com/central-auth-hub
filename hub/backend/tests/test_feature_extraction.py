"""Tests — extract_session_features (21 features, contract กับ ml-service/features.py).

ครอบ:
  - คืน 21 ตัวเป๊ะ (ตัด is_weekend + has_passkey, เพิ่ม 6)
  - ลำดับถูก (spot-check ตำแหน่งสำคัญ)
  - feature ใหม่คำนวณถูก: concurrent_session_count, active_subsystem_count,
    weekday_usage_score, scope_sensitivity_score, permission_change_age,
    confirmed_incident_count
  - cold start: user ใหม่ → personalized = neutral
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import AccessList, LoginSession, Subsystem, User
from app.services.feature_extraction import (
    PERM_AGE_NEUTRAL,
    extract_session_features,
)

# index map (0-based) ตาม ml-service/app/features.py
IDX = {
    "passkey_count": 11,
    "concurrent_session_count": 15,
    "active_subsystem_count": 16,
    "weekday_usage_score": 17,
    "scope_sensitivity_score": 18,
    "permission_change_age": 19,
    "confirmed_incident_count": 20,
}


@pytest.mark.smoke
def test_rule_engine_feat_map_aligned():
    """rule_engine.FEAT ต้องตรงกับลำดับ 21 features (contract B27).

    กัน regression: ถ้าตัด/เพิ่ม/สลับ feature แล้วลืมอัปเดต FEAT →
    rule+behavior อ่าน feature ผิดตำแหน่ง → score มั่ว (บั๊ก 2026-06-15).
    """
    from app.security.rule_engine import FEAT

    assert "is_weekend" not in FEAT  # ตัดแล้ว
    assert "has_passkey" not in FEAT  # ตัดแล้ว
    assert len(FEAT) == 21
    # indices ต้อง unique + ครบ 0..20
    assert sorted(FEAT.values()) == list(range(21))
    # ตำแหน่งสำคัญ (ที่ rule/behavior ใช้จริง)
    assert FEAT["hours_from_typical_login_time"] == 2
    assert FEAT["is_thailand"] == 3
    assert FEAT["is_new_country"] == 4
    assert FEAT["is_new_device"] == 6
    assert FEAT["failed_logins_24h"] == 10


@pytest.mark.smoke
def test_benign_login_low_rule_score(db):
    """vector ปกติ (geo NULL = dev, ไม่มี signal) → rule score ต่ำ ไม่ใช่ 1.0.

    regression: บั๊ก FEAT misalign ทำให้ login ปกติพุ่ง 1.000 (2026-06-15).
    """
    from app.security.rule_engine import evaluate_rules

    # 21-feature vector: คนปกติ — ไม่มี new device/country, failed=0, ไม่มี passkey signal
    feats = [10, 2, 1, 1, 0, 0, 0, 0, 4, 2, 0, 0, 0, 0, 0, 1, 1, 0.1, 0.3, 500, 0]
    res = evaluate_rules(
        feats, db, user_id=str(uuid.uuid4()), ip="203.0.113.9", geo_country=None
    )
    assert not res.blocked
    assert (
        res.score <= 0.2
    ), f"login ปกติไม่ควรได้ rule score สูง — ได้ {res.score} ({res.reasons})"


@pytest.fixture
def db() -> Session:
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def user(db: Session) -> User:
    u = User(
        email=f"feat-{uuid.uuid4().hex[:8]}@uni.ac.th",
        full_name="Feature Tester",
        user_type="staff",
        identifier=f"S{uuid.uuid4().hex[:4]}",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    yield u
    db.query(AccessList).filter(AccessList.user_id == u.id).delete()
    db.query(LoginSession).filter(LoginSession.user_id == u.id).delete()
    db.delete(u)
    db.commit()


def _add_session(db, user, **kw):
    s = LoginSession(
        user_id=user.id,
        ip=kw.get("ip", "1.2.3.4"),
        user_agent=kw.get("user_agent", "Mozilla/5.0"),
        geo_country=kw.get("geo_country", "TH"),
        decision=kw.get("decision", "pass"),
        created_at=kw.get("created_at", datetime.utcnow()),
        logout_at=kw.get("logout_at"),
        subsystem_id=kw.get("subsystem_id"),
        is_account_takeover=kw.get("is_account_takeover", False),
        is_attack_ip=kw.get("is_attack_ip", False),
    )
    db.add(s)
    db.commit()
    return s


# ─── contract: 21 features ───────────────────────────────────────────────────


@pytest.mark.smoke
def test_returns_exactly_21_features(user, db):
    feats = extract_session_features(db, user.id, "1.2.3.4", "Mozilla/5.0", "TH")
    assert len(feats) == 21


@pytest.mark.smoke
def test_cold_start_neutral(user, db):
    """user ใหม่ (ไม่มี history) → personalized/privilege = neutral."""
    feats = extract_session_features(db, user.id, "1.2.3.4", "Mozilla/5.0", "TH")
    assert feats[IDX["weekday_usage_score"]] == 0.0
    assert feats[IDX["permission_change_age"]] == PERM_AGE_NEUTRAL
    assert feats[IDX["confirmed_incident_count"]] == 0.0
    assert feats[IDX["passkey_count"]] == 0.0


# ─── concurrent + active_subsystem ──────────────────────────────────────────


@pytest.mark.smoke
def test_concurrent_session_count_active_only(user, db):
    """นับเฉพาะ active (logout_at NULL) + ภายใน 60 นาที."""
    now = datetime.utcnow()
    _add_session(db, user, created_at=now - timedelta(minutes=5))  # active
    _add_session(db, user, created_at=now - timedelta(minutes=10))  # active
    _add_session(
        db, user, created_at=now - timedelta(minutes=5), logout_at=now
    )  # ปิดแล้ว
    _add_session(db, user, created_at=now - timedelta(hours=3))  # เก่าเกิน window
    feats = extract_session_features(
        db, user.id, "1.2.3.4", "Mozilla/5.0", "TH", now=now
    )
    assert feats[IDX["concurrent_session_count"]] == 2.0


@pytest.mark.smoke
def test_active_subsystem_count_distinct(user, db):
    """นับ subsystem distinct ที่ active (lateral movement)."""
    now = datetime.utcnow()
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    # ต้องมี subsystem จริงใน DB เพราะ FK
    for sid, name in [(s1, "sub-a"), (s2, "sub-b")]:
        db.add(
            Subsystem(
                id=sid,
                name=f"{name}-{uuid.uuid4().hex[:4]}",
                client_id=f"cli_{uuid.uuid4().hex[:8]}",
                client_secret_hash="x",
                redirect_uris=["http://localhost/cb"],
                scope=["email", "name"],
                status="active",
            )
        )
    db.commit()
    _add_session(db, user, created_at=now - timedelta(minutes=2), subsystem_id=s1)
    _add_session(db, user, created_at=now - timedelta(minutes=3), subsystem_id=s2)
    _add_session(db, user, created_at=now - timedelta(minutes=4), subsystem_id=s1)  # ซ้ำ
    try:
        feats = extract_session_features(
            db, user.id, "1.2.3.4", "Mozilla/5.0", "TH", now=now
        )
        assert feats[IDX["active_subsystem_count"]] == 2.0
    finally:
        db.query(LoginSession).filter(LoginSession.user_id == user.id).delete()
        db.query(Subsystem).filter(Subsystem.id.in_([s1, s2])).delete()
        db.commit()


# ─── confirmed_incident_count (ground-truth) ────────────────────────────────


@pytest.mark.smoke
def test_confirmed_incident_count(user, db):
    now = datetime.utcnow()
    _add_session(db, user, created_at=now - timedelta(days=1), is_account_takeover=True)
    _add_session(db, user, created_at=now - timedelta(days=2), is_attack_ip=True)
    _add_session(db, user, created_at=now - timedelta(days=3))  # ปกติ
    feats = extract_session_features(
        db, user.id, "1.2.3.4", "Mozilla/5.0", "TH", now=now
    )
    assert feats[IDX["confirmed_incident_count"]] == 2.0


# ─── permission_change_age ──────────────────────────────────────────────────


@pytest.mark.smoke
def test_permission_change_age_recent(user, db):
    """access_list เพิ่งเปลี่ยน → age น้อย."""
    now = datetime.utcnow()
    sid = uuid.uuid4()
    db.add(
        Subsystem(
            id=sid,
            name=f"perm-{uuid.uuid4().hex[:4]}",
            client_id=f"cli_{uuid.uuid4().hex[:8]}",
            client_secret_hash="x",
            redirect_uris=["http://localhost/cb"],
            scope=["email"],
            status="active",
        )
    )
    db.commit()
    db.add(
        AccessList(
            subsystem_id=sid,
            user_id=user.id,
            role_in_sub="member",
            granted_at=now - timedelta(days=2),
        )
    )
    db.commit()
    try:
        feats = extract_session_features(
            db, user.id, "1.2.3.4", "Mozilla/5.0", "TH", now=now
        )
        age = feats[IDX["permission_change_age"]]
        assert 1.5 < age < 2.5  # ~2 วัน
    finally:
        db.query(AccessList).filter(AccessList.user_id == user.id).delete()
        db.query(Subsystem).filter(Subsystem.id == sid).delete()
        db.commit()


# ─── scope_sensitivity_score ────────────────────────────────────────────────


@pytest.mark.smoke
def test_scope_sensitivity_from_subsystem(user, db):
    """scope ที่ sensitive (student_id) → score สูงกว่า scope ทั่วไป (email)."""
    sid = uuid.uuid4()
    db.add(
        Subsystem(
            id=sid,
            name=f"scope-{uuid.uuid4().hex[:4]}",
            client_id=f"cli_{uuid.uuid4().hex[:8]}",
            client_secret_hash="x",
            redirect_uris=["http://localhost/cb"],
            scope=["email", "name", "student_id"],  # 0.1+0.1+0.6 = 0.8
            status="active",
        )
    )
    db.commit()
    try:
        feats = extract_session_features(
            db, user.id, "1.2.3.4", "Mozilla/5.0", "TH", subsystem_id=sid
        )
        assert feats[IDX["scope_sensitivity_score"]] == pytest.approx(0.8, abs=0.01)
        # ไม่มี subsystem → 0
        feats_none = extract_session_features(
            db, user.id, "1.2.3.4", "Mozilla/5.0", "TH"
        )
        assert feats_none[IDX["scope_sensitivity_score"]] == 0.0
    finally:
        db.query(Subsystem).filter(Subsystem.id == sid).delete()
        db.commit()
