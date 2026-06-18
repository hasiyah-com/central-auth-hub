"""Cross-subsystem risk propagation (rule layer).

แนวคิด: ระบบย่อย *อื่น* เพิ่งมี login เสี่ยงสูง (เช่น ระบบ 1 ได้ risk 0.7) →
พอ user เข้าระบบนี้ (ระบบ 2) ให้ rule engine escalate (เข้มขึ้น).

ทำเป็น rule (inference-time policy) ไม่ใช่ ML feature → เลี่ยง feedback loop
(ไม่เอา risk_score ไป train), explainable ผ่าน rule reasons.
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import LoginSession, Subsystem, User
from app.security.rule_engine import (
    CROSS_SUBSYSTEM_BOOST_FACTOR,
    evaluate_rules,
)

# benign 23-feature vector — ไม่มี rule อื่นยิง (จะได้วัดเฉพาะ cross boost)
BENIGN = [10, 2, 1, 1, 0, 0, 0, 0, 4, 2, 0, 0, 0, 0, 0, 1, 1, 0.1, 0.3, 0, 365, 0, 0]


@pytest.fixture
def db() -> Session:
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def setup(db: Session):
    """user + 2 subsystems. cleanup ครบ."""
    u = User(
        email=f"cross-{uuid.uuid4().hex[:8]}@uni.ac.th",
        full_name="Cross Tester",
        user_type="student",
        identifier=f"65{uuid.uuid4().hex[:4]}",
    )
    db.add(u)
    sub1, sub2 = uuid.uuid4(), uuid.uuid4()
    for sid, name in [(sub1, "sys1"), (sub2, "sys2")]:
        db.add(
            Subsystem(
                id=sid,
                name=f"{name}-{uuid.uuid4().hex[:4]}",
                client_id=f"cli_{uuid.uuid4().hex[:8]}",
                client_secret_hash="x",
                redirect_uris=["http://localhost/cb"],
                scope=["email"],
                status="active",
            )
        )
    db.commit()
    db.refresh(u)
    yield u, sub1, sub2
    db.query(LoginSession).filter(LoginSession.user_id == u.id).delete()
    db.query(Subsystem).filter(Subsystem.id.in_([sub1, sub2])).delete()
    db.delete(u)
    db.commit()


def _add_login(db, user_id, sub_id, risk, minutes_ago):
    db.add(
        LoginSession(
            user_id=user_id,
            subsystem_id=sub_id,
            ip="1.2.3.4",
            decision="would_warn",
            risk_score=risk,
            created_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
        )
    )
    db.commit()


@pytest.mark.smoke
def test_cross_subsystem_risk_escalates(setup, db):
    """ระบบ 1 เสี่ยง 0.7 เมื่อ 5 นาทีก่อน → เข้าระบบ 2 ต้องได้ boost (graded)."""
    user, sub1, sub2 = setup
    _add_login(db, user.id, sub1, 0.7, minutes_ago=5)

    res = evaluate_rules(BENIGN, db, str(user.id), "9.9.9.9", None, subsystem_id=sub2)

    assert any("cross_subsystem_risk" in r for r in res.reasons), res.reasons
    # boost = 0.7 * factor
    assert res.score == pytest.approx(0.7 * CROSS_SUBSYSTEM_BOOST_FACTOR, abs=0.01)


@pytest.mark.smoke
def test_cross_subsystem_same_subsystem_no_boost(setup, db):
    """เสี่ยงในระบบเดียวกัน (ไม่ใช่ระบบอื่น) → ไม่ propagate."""
    user, sub1, sub2 = setup
    _add_login(db, user.id, sub1, 0.7, minutes_ago=5)

    res = evaluate_rules(BENIGN, db, str(user.id), "9.9.9.9", None, subsystem_id=sub1)
    assert not any("cross_subsystem_risk" in r for r in res.reasons)
    assert res.score == 0.0


@pytest.mark.smoke
def test_cross_subsystem_old_session_no_boost(setup, db):
    """เสี่ยงเมื่อ 45 นาทีก่อน (เกิน window 30) → ไม่ propagate."""
    user, sub1, sub2 = setup
    _add_login(db, user.id, sub1, 0.9, minutes_ago=45)

    res = evaluate_rules(BENIGN, db, str(user.id), "9.9.9.9", None, subsystem_id=sub2)
    assert not any("cross_subsystem_risk" in r for r in res.reasons)


@pytest.mark.smoke
def test_cross_subsystem_low_risk_no_boost(setup, db):
    """ระบบอื่นเสี่ยงต่ำ (0.3 < threshold 0.6) → ไม่ propagate."""
    user, sub1, sub2 = setup
    _add_login(db, user.id, sub1, 0.3, minutes_ago=5)

    res = evaluate_rules(BENIGN, db, str(user.id), "9.9.9.9", None, subsystem_id=sub2)
    assert not any("cross_subsystem_risk" in r for r in res.reasons)


@pytest.mark.smoke
def test_cross_subsystem_hub_direct_skipped(setup, db):
    """Hub-direct (subsystem_id=None) → ไม่ทำ cross check (ไม่ crash)."""
    user, sub1, sub2 = setup
    _add_login(db, user.id, sub1, 0.9, minutes_ago=5)

    res = evaluate_rules(BENIGN, db, str(user.id), "9.9.9.9", None, subsystem_id=None)
    assert not any("cross_subsystem_risk" in r for r in res.reasons)
