"""Tests — point-in-time correctness ของ extract_session_features (กัน data leakage).

**ปัญหาที่ test นี้กันไว้:**
`extract_session_features(now=...)` ถูกใช้ 2 แบบ
  1. **ตอน login จริง** — `now = utcnow()` (ไม่มี session ในอนาคต → ไม่มีปัญหา)
  2. **ตอน re-score ย้อนหลัง** — `now = session.created_at` ใช้โดย 5 scripts:
     `export_labeled_data.py` (สร้าง training data), `evaluate_on_real.py`,
     `evaluate_real_logins.py`, `calibrate_thresholds.py`, `check_feature_drift.py`

ถ้า query ประวัติไม่กรอง `created_at < now` → feature ย้อนหลัง **"มองเห็นอนาคต"**
(data leakage) ทำให้ training data / metric / threshold ที่ได้เพี้ยนทั้งหมด

หลักฐานที่เจอจริง: session ที่ลงวันที่ 8 วันก่อน รายงาน `login_count_24h = 78`
เพราะไปนับ session ของวันนี้เข้ามาด้วย → โดน hard block ทั้งที่เป็นพฤติกรรมปกติ

รัน:
    docker compose exec hub-backend pytest tests/test_feature_point_in_time.py -v
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.models import AccessList, LoginSession, PasskeyCredential, User
from app.services.feature_extraction import extract_session_features

# index ตาม rule_engine.FEAT (ดู docs/references.md §6)
F_HOURS_FROM_TYPICAL = 2
F_IS_NEW_COUNTRY = 4
F_COUNTRY_CHANGE_30D = 5
F_IS_NEW_DEVICE = 6
F_IS_NEW_UA_FAMILY = 7
F_LOG_MIN_SINCE_LAST = 8
F_LOGIN_COUNT_24H = 9
F_FAILED_24H = 10
F_PASSKEY_COUNT = 11
F_CONCURRENT = 15
F_WEEKDAY_USAGE = 17
F_EVER_CHANGED_PERM = 19
F_INCIDENT_COUNT = 21

UA_OLD = "Mozilla/5.0 (Windows NT 10.0) Chrome/120.0.0.0 Safari/537.36"
UA_FUTURE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Version/17.0 Mobile Safari/604.1"


def _mk_user(db) -> User:
    s = uuid.uuid4().hex[:8]
    u = User(
        email=f"pit_{s}@uni.ac.th",
        google_sub=f"gsub_{s}",
        full_name=f"PIT {s}",
        user_type="teacher",
        status="active",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _add_session(
    db,
    user,
    *,
    created_at,
    ip="203.0.113.1",
    ua=UA_OLD,
    country="TH",
    decision="pass",
    logout_at=None,
    attack=False,
):
    s = LoginSession(
        user_id=user.id,
        ip=ip,
        user_agent=ua,
        geo_country=country,
        decision=decision,
        created_at=created_at,
        logout_at=logout_at,
        is_attack_ip=attack,
    )
    db.add(s)
    db.commit()
    return s


def _purge(db, uid):
    db.query(LoginSession).filter(LoginSession.user_id == uid).delete(
        synchronize_session=False
    )
    db.query(PasskeyCredential).filter(PasskeyCredential.user_id == uid).delete(
        synchronize_session=False
    )
    db.query(AccessList).filter(AccessList.user_id == uid).delete(
        synchronize_session=False
    )
    db.query(User).filter(User.id == uid).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def u(db):
    user = _mk_user(db)
    uid = user.id
    yield user
    _purge(db, uid)


@pytest.fixture
def t():
    """3 จุดเวลา: อดีต (T0) → จุดที่ประเมิน (T1) → อนาคต (T2)."""
    t1 = datetime.utcnow().replace(microsecond=0) - timedelta(days=5)
    return {
        "past": t1 - timedelta(hours=2),
        "now": t1,
        "future": t1 + timedelta(hours=2),
    }


def _feats(db, user, t, *, ua=UA_OLD, country="TH"):
    return extract_session_features(
        db, user.id, ip="203.0.113.1", user_agent=ua, geo_country=country, now=t["now"]
    )


# ─────────────────────────────────────────────────────────────
# Velocity — นับเฉพาะก่อน now
# ─────────────────────────────────────────────────────────────


def test_login_count_24h_excludes_future(u, db, t):
    """login_count_24h ต้องไม่นับ session ที่เกิดหลัง now."""
    _add_session(db, u, created_at=t["past"])
    for i in range(5):  # session ในอนาคต 5 ครั้ง
        _add_session(db, u, created_at=t["future"] + timedelta(minutes=i))
    f = _feats(db, u, t)
    assert f[F_LOGIN_COUNT_24H] == 1.0, "ต้องนับแค่ session อดีต 1 ครั้ง ไม่รวมอนาคต 5 ครั้ง"


def test_failed_logins_24h_excludes_future(u, db, t):
    _add_session(db, u, created_at=t["past"], decision="pass")
    for i in range(3):
        _add_session(
            db, u, created_at=t["future"] + timedelta(minutes=i), decision="block"
        )
    f = _feats(db, u, t)
    assert f[F_FAILED_24H] == 0.0, "block ในอนาคตต้องไม่ถูกนับ"


def test_minutes_since_last_login_uses_past_not_future(u, db, t):
    """log_minutes_since_last_login ต้องวัดจาก session ก่อนหน้า ไม่ใช่ของอนาคต."""
    _add_session(db, u, created_at=t["past"])  # ห่าง 2 ชม. = 120 นาที
    _add_session(db, u, created_at=t["future"])
    f = _feats(db, u, t)
    import math

    expected = math.log(120.0)
    assert f[F_LOG_MIN_SINCE_LAST] == pytest.approx(
        expected, abs=0.05
    ), "ต้องคิดจาก session อดีต (120 นาที) ไม่ใช่ของอนาคต"


# ─────────────────────────────────────────────────────────────
# Geographic — ประเทศที่ "เคยเห็น" ต้องเป็นอดีตเท่านั้น
# ─────────────────────────────────────────────────────────────


def test_is_new_country_ignores_future_sessions(u, db, t):
    """เคย login US เฉพาะในอนาคต → ณ เวลา now ยังต้องถือว่า US เป็นประเทศใหม่."""
    _add_session(db, u, created_at=t["past"], country="TH")
    _add_session(db, u, created_at=t["future"], country="US")
    f = _feats(db, u, t, country="US")
    assert f[F_IS_NEW_COUNTRY] == 1.0, "US ยังไม่เคยพบ ณ เวลานั้น → ต้องเป็นประเทศใหม่"


def test_country_change_30d_excludes_future(u, db, t):
    _add_session(db, u, created_at=t["past"], country="TH")
    _add_session(db, u, created_at=t["future"], country="US")
    _add_session(db, u, created_at=t["future"] + timedelta(hours=1), country="RU")
    f = _feats(db, u, t, country="TH")
    assert f[F_COUNTRY_CHANGE_30D] == 1.0, "นับได้แค่ TH (อดีต) ไม่รวม US/RU ในอนาคต"


# ─────────────────────────────────────────────────────────────
# Device — อุปกรณ์ที่ "เคยใช้" ต้องเป็นอดีตเท่านั้น
# ─────────────────────────────────────────────────────────────


def test_is_new_device_ignores_future_sessions(u, db, t):
    """เคยใช้ iPhone เฉพาะในอนาคต → ณ เวลา now ยังต้องเป็นอุปกรณ์ใหม่."""
    _add_session(db, u, created_at=t["past"], ua=UA_OLD)
    _add_session(db, u, created_at=t["future"], ua=UA_FUTURE)
    f = _feats(db, u, t, ua=UA_FUTURE)
    assert f[F_IS_NEW_DEVICE] == 1.0
    assert f[F_IS_NEW_UA_FAMILY] == 1.0, "Safari ยังไม่เคยพบ ณ เวลานั้น"


# ─────────────────────────────────────────────────────────────
# Temporal (personalized) — baseline ต้องมาจากอดีต
# ─────────────────────────────────────────────────────────────


def test_typical_hour_baseline_excludes_future(u, db, t):
    """cold start: มีแต่ session อนาคต → ต้องได้ neutral (0.0) ไม่ใช่คำนวณจากอนาคต."""
    for i in range(10):
        _add_session(db, u, created_at=t["future"] + timedelta(days=i))
    f = _feats(db, u, t)
    assert f[F_HOURS_FROM_TYPICAL] == 0.0, "history อนาคตไม่นับ → cold start neutral"
    assert f[F_WEEKDAY_USAGE] == 0.0


# ─────────────────────────────────────────────────────────────
# Session / History / Credential
# ─────────────────────────────────────────────────────────────


def test_concurrent_session_excludes_future(u, db, t):
    for i in range(4):
        _add_session(db, u, created_at=t["future"] + timedelta(minutes=i))
    f = _feats(db, u, t)
    assert f[F_CONCURRENT] == 0.0, "session ที่ยังไม่เกิด ไม่ควรนับเป็น concurrent"


def test_confirmed_incident_excludes_future(u, db, t):
    """incident ที่เกิดหลัง now ต้องไม่ถูกนับ (กัน label leakage ที่ร้ายแรงที่สุด)."""
    _add_session(db, u, created_at=t["past"])
    _add_session(db, u, created_at=t["future"], attack=True)
    f = _feats(db, u, t)
    assert f[F_INCIDENT_COUNT] == 0.0, "incident ในอนาคต = label leakage ต้องไม่นับ"


def test_passkey_count_excludes_future_credentials(u, db, t):
    """passkey ที่ลงทะเบียนหลัง now ต้องไม่ถูกนับ."""
    db.add(
        PasskeyCredential(
            user_id=u.id,
            credential_id=uuid.uuid4().bytes + uuid.uuid4().bytes,
            public_key=b"\x00" * 32,
            sign_count=0,
            device_name="future device",
            status="ACTIVE",
            created_at=t["future"],
        )
    )
    db.commit()
    f = _feats(db, u, t)
    assert f[F_PASSKEY_COUNT] == 0.0, "passkey ที่ยังไม่ถูกสร้าง ณ เวลานั้น ต้องไม่นับ"


def test_permission_change_excludes_future(u, db, t):
    """สิทธิ์ที่เปลี่ยนหลัง now ต้องไม่ทำให้ ever_changed_permission = 1."""
    from app.models import Subsystem

    sub = db.query(Subsystem).first()
    if sub is None:
        pytest.skip("ไม่มี subsystem ใน DB สำหรับทดสอบ access_list")
    db.add(AccessList(user_id=u.id, subsystem_id=sub.id, granted_at=t["future"]))
    db.commit()
    f = _feats(db, u, t)
    assert f[F_EVER_CHANGED_PERM] == 0.0, "การเปลี่ยนสิทธิ์ในอนาคตต้องไม่ถูกมองเห็น"


# ─────────────────────────────────────────────────────────────
# Regression — พฤติกรรมตอน login จริงต้องไม่เปลี่ยน
# ─────────────────────────────────────────────────────────────


def test_live_login_unaffected(u, db):
    """ตอน login จริง (now=utcnow, ไม่มี session อนาคต) ผลต้องเหมือนเดิมทุกประการ."""
    base = datetime.utcnow() - timedelta(hours=1)
    for i in range(3):
        _add_session(db, u, created_at=base - timedelta(minutes=i * 10))
    f = extract_session_features(
        db, u.id, ip="203.0.113.1", user_agent=UA_OLD, geo_country="TH"
    )
    assert len(f) == 23
    assert f[F_LOGIN_COUNT_24H] == 3.0, "นับ session อดีตครบตามปกติ"
    assert f[F_IS_NEW_COUNTRY] == 0.0
    assert f[F_IS_NEW_DEVICE] == 0.0
