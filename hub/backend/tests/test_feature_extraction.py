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
    PERM_AGE_CAP,
    extract_session_features,
)

# index map (0-based) ตาม ml-service/app/features.py (22 features)
IDX = {
    "is_new_device": 6,
    "is_new_user_agent_family": 7,
    "passkey_count": 11,
    "concurrent_session_count": 15,
    "active_subsystem_count": 16,
    "weekday_usage_score": 17,
    "scope_sensitivity_score": 18,
    "ever_changed_permission": 19,
    "permission_change_age": 20,
    "confirmed_incident_count": 21,
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
    assert len(FEAT) == 23
    # indices ต้อง unique + ครบ 0..21
    assert sorted(FEAT.values()) == list(range(23))
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

    # 23-feature vector: คนปกติ — ไม่มี new device/country, failed=0, ไม่มี passkey signal
    # [..., scope=0.3, ever_changed=0, perm_age=365, confirmed=0, impossible_travel=0]
    feats = [10, 2, 1, 1, 0, 0, 0, 0, 4, 2, 0, 0, 0, 0, 0, 1, 1, 0.1, 0.3, 0, 365, 0, 0]
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
def test_returns_exactly_23_features(user, db):
    feats = extract_session_features(db, user.id, "1.2.3.4", "Mozilla/5.0", "TH")
    assert len(feats) == 23


@pytest.mark.smoke
def test_cold_start_neutral(user, db):
    """user ใหม่ (ไม่มี history) → personalized/privilege = neutral."""
    feats = extract_session_features(db, user.id, "1.2.3.4", "Mozilla/5.0", "TH")
    assert feats[IDX["weekday_usage_score"]] == 0.0
    assert feats[IDX["ever_changed_permission"]] == 0.0  # ไม่เคยเปลี่ยน
    assert feats[IDX["permission_change_age"]] == PERM_AGE_CAP  # = 365
    assert feats[IDX["confirmed_incident_count"]] == 0.0
    assert feats[IDX["passkey_count"]] == 0.0


# ─── is_new_device: device signature เสถียรข้าม browser build (B56) ──────────

# เครื่อง/OS/เบราว์เซอร์เดิม ต่างแค่เลข build (Chrome auto-update)
_UA_CHROME_150 = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
_UA_CHROME_151 = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
_UA_IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"


@pytest.mark.smoke
def test_new_device_ignores_browser_build_bump(user, db):
    """B56: Chrome อัปเดต build (150→151) บนเครื่องเดิม → ไม่ใช่ 'เครื่องใหม่'.

    เดิมเทียบ UA string เต็ม → build ต่าง = is_new_device=1 (false positive สวิง).
    ตอนนี้เทียบ device signature (OS+device+family) → 150 กับ 151 = เครื่องเดิม → 0.
    """
    _add_session(
        db,
        user,
        user_agent=_UA_CHROME_150,
        created_at=datetime.utcnow() - timedelta(days=2),
    )
    feats = extract_session_features(db, user.id, "1.2.3.4", _UA_CHROME_151, "TH")
    assert feats[IDX["is_new_device"]] == 0.0, "Chrome build bump ไม่ควรนับเป็นเครื่องใหม่"
    assert feats[IDX["is_new_user_agent_family"]] == 0.0, "browser family เดิม (Chrome)"


@pytest.mark.smoke
def test_new_device_detects_genuinely_new_device(user, db):
    """เครื่องใหม่จริง (Windows Chrome → iPhone Safari) → is_new_device=1."""
    _add_session(
        db,
        user,
        user_agent=_UA_CHROME_150,
        created_at=datetime.utcnow() - timedelta(days=2),
    )
    feats = extract_session_features(db, user.id, "1.2.3.4", _UA_IPHONE, "TH")
    assert feats[IDX["is_new_device"]] == 1.0, "OS+device+family ต่าง → เครื่องใหม่จริง"


# ─── trusted-device history: session ที่ถูก flag ต้องไม่ whitelist ตัวเอง (B57) ──


@pytest.mark.smoke
def test_flagged_session_does_not_trust_its_own_device(user, db):
    """B57: would_block ครั้งแรก → ครั้งที่สองจากเครื่องเดิมต้องยัง is_new_device=1.

    เดิม seen-device query ไม่กรอง decision → row ที่เพิ่งถูก flag นับเป็น "เคยเห็น"
    ทำให้เครื่องที่ระบบเพิ่งเตือน whitelist ตัวเองในครั้งถัดไป (score ร่วง 0.9→0.1).
    """
    # เครื่องที่ไว้ใจได้: Windows/Chrome (allow)
    _add_session(
        db,
        user,
        user_agent=_UA_CHROME_150,
        decision="allow",
        created_at=datetime.utcnow() - timedelta(days=3),
    )
    # เครื่องแปลกหน้าที่โดน flag — ต้องไม่ทำให้ตัวเองกลายเป็นเครื่องที่รู้จัก
    _add_session(
        db,
        user,
        user_agent=_UA_IPHONE,
        decision="would_block",
        created_at=datetime.utcnow() - timedelta(minutes=10),
    )

    feats = extract_session_features(db, user.id, "1.2.3.4", _UA_IPHONE, "TH")
    assert feats[IDX["is_new_device"]] == 1.0, "would_block ต้องไม่นับเป็นประวัติที่ไว้ใจได้"


@pytest.mark.smoke
def test_mfa_passed_makes_device_trusted(user, db):
    """ถูก challenge แล้วยืนยันตัวตนผ่านจริง (mfa_passed) → เครื่องนั้นเป็น trusted."""
    _add_session(
        db,
        user,
        user_agent=_UA_CHROME_150,
        decision="allow",
        created_at=datetime.utcnow() - timedelta(days=3),
    )
    _add_session(
        db,
        user,
        user_agent=_UA_IPHONE,
        decision="mfa_passed",
        created_at=datetime.utcnow() - timedelta(minutes=10),
    )

    feats = extract_session_features(db, user.id, "1.2.3.4", _UA_IPHONE, "TH")
    assert feats[IDX["is_new_device"]] == 0.0, "ยืนยันตัวตนผ่านแล้ว → ไว้ใจเครื่องนี้ได้"


@pytest.mark.smoke
def test_warn_is_not_trusted(user, db):
    """warn = login สำเร็จแต่ไม่ได้ยืนยันตัวตนเพิ่ม → ยังไม่นับเป็น trusted (เข้มไว้ก่อน)."""
    _add_session(
        db,
        user,
        user_agent=_UA_CHROME_150,
        decision="allow",
        created_at=datetime.utcnow() - timedelta(days=3),
    )
    _add_session(
        db,
        user,
        user_agent=_UA_IPHONE,
        decision="warn",
        created_at=datetime.utcnow() - timedelta(minutes=10),
    )

    feats = extract_session_features(db, user.id, "1.2.3.4", _UA_IPHONE, "TH")
    assert feats[IDX["is_new_device"]] == 1.0


@pytest.mark.smoke
def test_legacy_pass_decision_still_trusted(user, db):
    """legacy 'pass' (ยุคก่อน 4-layer) ต้องยังไว้ใจได้ — ไม่งั้นประวัติเดิมทุกคนถูกล้าง."""
    _add_session(
        db,
        user,
        user_agent=_UA_CHROME_150,
        decision="pass",
        created_at=datetime.utcnow() - timedelta(days=3),
    )

    feats = extract_session_features(db, user.id, "1.2.3.4", _UA_CHROME_151, "TH")
    assert feats[IDX["is_new_device"]] == 0.0


@pytest.mark.smoke
def test_no_trusted_history_treats_every_device_as_new(user, db):
    """มีประวัติแต่ไม่มี login ที่พิสูจน์แล้วเลย → ทุกเครื่องเป็นเครื่องใหม่.

    กันช่องที่ว่า "กรอง untrusted ออกจนเซตว่าง" แล้วตกไปเป็น cold-start neutral (0)
    ซึ่งจะกลายเป็นให้คะแนน attacker ต่ำลงแทนที่จะสูงขึ้น.
    """
    _add_session(
        db,
        user,
        user_agent=_UA_CHROME_150,
        decision="would_block",
        created_at=datetime.utcnow() - timedelta(hours=2),
    )

    feats = extract_session_features(db, user.id, "1.2.3.4", _UA_IPHONE, "TH")
    assert feats[IDX["is_new_device"]] == 1.0
    assert feats[IDX["is_new_user_agent_family"]] == 1.0


@pytest.mark.smoke
def test_true_cold_start_still_neutral(user, db):
    """user ใหม่จริง (ไม่มี session เลย) → ยัง neutral (0) ไม่ถูกลงโทษ."""
    feats = extract_session_features(db, user.id, "1.2.3.4", _UA_CHROME_150, "TH")
    assert feats[IDX["is_new_device"]] == 0.0
    assert feats[IDX["is_new_user_agent_family"]] == 0.0


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
