"""Risk scenarios — ทดสอบ RBA กับสถานการณ์ login จริง 3 แบบ.

สถานการณ์ที่ครอบ:
  1. **ปกติ (baseline)** — ประเทศ/อุปกรณ์/เวลาเดิม → ความเสี่ยงต่ำ
  2. **ผิดปกติ** — IP + ประเทศใหม่ / เวลาผิดจากปกติ / อุปกรณ์ใหม่ → เสี่ยงสูงกว่า baseline
  3. **Impossible travel** — login ประเทศหนึ่ง ผ่านไป 10 นาที login อีกประเทศ → เสี่ยงสูงสุด

ทดสอบ 2 ชั้น:
  - `extract_session_features()` — ค่า feature ที่คำนวณได้ (deterministic ยืนยันได้แน่นอน)
  - `evaluate_login_risk()` — คะแนนรวม 4 ชั้น (rule + behavior + iforest + aggregation)
    ยืนยันแบบ **เปรียบเทียบ** (ผิดปกติ > ปกติ) แทนค่าคงที่ เพราะ iforest มี noise
    และ threshold ปรับได้ — การเทียบลำดับจึงเสถียรกว่า

รัน:
    docker compose exec hub-backend pytest tests/test_risk_scenarios.py -v
    docker compose exec hub-backend pytest tests/test_risk_scenarios.py -v -s   # เห็น print คะแนน
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.models import AuditLog, LoginSession, User
from app.security.risk_engine import evaluate_login_risk
from app.services.feature_extraction import (
    MIN_HISTORY_FOR_PERSONALIZATION,
    extract_session_features,
)

# ── index ของ feature ตาม rule_engine.FEAT (ต้อง sync กับ feature_extraction) ──
F_HOUR = 0
F_HOURS_FROM_TYPICAL = 2
F_IS_THAILAND = 3
F_IS_NEW_COUNTRY = 4
F_COUNTRY_CHANGE_30D = 5
F_IS_NEW_DEVICE = 6
F_IS_NEW_UA_FAMILY = 7
F_IMPOSSIBLE_TRAVEL = 22

# ค่าคงที่ของ "พฤติกรรมปกติ" ที่ใช้ seed history
UA_USUAL = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
UA_NEW = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
IP_USUAL = "203.0.113.10"  # TEST-NET-3 (RFC 5737)
IP_NEW = "198.51.100.77"  # TEST-NET-2
USUAL_HOUR = 9  # user คนนี้ปกติ login ~9 โมง


# ─────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────


def _mk_user(db) -> User:
    s = uuid.uuid4().hex[:8]
    u = User(
        email=f"risk_{s}@uni.ac.th",
        google_sub=f"gsub_{s}",
        full_name=f"Risk Test {s}",
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
    created_at: datetime,
    ip: str = IP_USUAL,
    user_agent: str = UA_USUAL,
    country: str | None = "TH",
    decision: str = "pass",
) -> LoginSession:
    """เพิ่ม login history 1 แถว (ใช้สร้าง 'พฤติกรรมปกติ' ให้ user)."""
    s = LoginSession(
        user_id=user.id,
        ip=ip,
        user_agent=user_agent,
        geo_country=country,
        decision=decision,
        created_at=created_at,
    )
    db.add(s)
    db.commit()
    return s


def _seed_normal_history(db, user, *, base: datetime, days: int = 8) -> None:
    """สร้างประวัติ 'ปกติ': ไทย · อุปกรณ์เดิม · IP เดิม · ~9 โมง ทุกวัน.

    จำนวน >= MIN_HISTORY_FOR_PERSONALIZATION เพื่อให้พ้น cold start
    (ไม่งั้น hours_from_typical จะเป็น 0.0 neutral เสมอ)
    """
    assert days >= MIN_HISTORY_FOR_PERSONALIZATION
    for i in range(days, 0, -1):
        _add_session(
            db,
            user,
            created_at=(base - timedelta(days=i)).replace(
                hour=USUAL_HOUR, minute=0, second=0, microsecond=0
            ),
        )


def _purge(db, uid):
    db.query(LoginSession).filter(LoginSession.user_id == uid).delete(
        synchronize_session=False
    )
    db.query(AuditLog).filter(AuditLog.actor_id == uid).delete(
        synchronize_session=False
    )
    db.query(User).filter(User.id == uid).delete(synchronize_session=False)
    db.commit()


@pytest.fixture
def user_with_history(db):
    """user ที่มีประวัติ login ปกติ 8 ครั้ง (ไทย/อุปกรณ์เดิม/9 โมง)."""
    u = _mk_user(db)
    uid = u.id
    base = datetime.utcnow().replace(hour=USUAL_HOUR, minute=0, second=0, microsecond=0)
    _seed_normal_history(db, u, base=base)
    u._base = base  # เก็บเวลาอ้างอิงไว้ใช้ในเทส
    yield u
    _purge(db, uid)


async def _score(db, user, *, ip, ua, country, now):
    """extract features → evaluate risk (enforce mode เพื่อให้เห็น decision จริง)."""
    feats = extract_session_features(
        db, user.id, ip=ip, user_agent=ua, geo_country=country, now=now
    )
    result = await evaluate_login_risk(
        features=feats,
        user_id=str(user.id),
        ip=ip,
        geo_country=country,
        db=db,
        shadow_mode=False,
    )
    return feats, result


# ═════════════════════════════════════════════════════════════
# 1. ปกติ (baseline) — ประเทศ/อุปกรณ์/เวลาเดิม
# ═════════════════════════════════════════════════════════════


def test_normal_login_features_are_clean(user_with_history, db):
    """login ปกติ: ไทย · อุปกรณ์เดิม · เวลาเดิม → ไม่มีสัญญาณผิดปกติ."""
    now = user_with_history._base.replace(hour=USUAL_HOUR)
    f = extract_session_features(
        db,
        user_with_history.id,
        ip=IP_USUAL,
        user_agent=UA_USUAL,
        geo_country="TH",
        now=now,
    )
    assert len(f) == 23, "feature vector ต้องมี 23 ตัว (sync กับ FEATURE_NAMES)"
    assert f[F_IS_THAILAND] == 1.0
    assert f[F_IS_NEW_COUNTRY] == 0.0
    assert f[F_IS_NEW_DEVICE] == 0.0
    assert f[F_IS_NEW_UA_FAMILY] == 0.0
    assert f[F_IMPOSSIBLE_TRAVEL] == 0.0
    assert f[F_HOURS_FROM_TYPICAL] == 0.0  # ตรงเวลาปกติเป๊ะ


@pytest.mark.asyncio
async def test_normal_login_risk_is_low(user_with_history, db):
    """baseline: คะแนนต่ำ + ไม่ถูกบล็อก."""
    now = user_with_history._base.replace(hour=USUAL_HOUR)
    _, r = await _score(
        db, user_with_history, ip=IP_USUAL, ua=UA_USUAL, country="TH", now=now
    )
    print(f"\n[ปกติ] score={r['score']:.3f} decision={r['decision']} {r['reasons']}")
    assert r["decision"] != "block"
    assert r["score"] < 0.85, "login ปกติต้องไม่ถึง hard block threshold"


# ═════════════════════════════════════════════════════════════
# 2. IP + ประเทศต่างจากเดิม / เวลาต่างจากเดิม
# ═════════════════════════════════════════════════════════════


def test_new_country_and_ip_flags_features(user_with_history, db):
    """IP + ประเทศใหม่ (TH → US) → is_new_country=1, is_thailand=0."""
    now = user_with_history._base.replace(hour=USUAL_HOUR)
    f = extract_session_features(
        db,
        user_with_history.id,
        ip=IP_NEW,
        user_agent=UA_USUAL,
        geo_country="US",
        now=now,
    )
    assert f[F_IS_THAILAND] == 0.0, "ประเทศไม่ใช่ไทย"
    assert f[F_IS_NEW_COUNTRY] == 1.0, "ไม่เคย login จากประเทศนี้มาก่อน"
    assert f[F_COUNTRY_CHANGE_30D] >= 0.0


def test_unusual_hour_flags_hours_from_typical(user_with_history, db):
    """ปกติ login 9 โมง → login ตี 3 = ห่างจากเวลาปกติ 6 ชม."""
    now = user_with_history._base.replace(hour=3)
    f = extract_session_features(
        db,
        user_with_history.id,
        ip=IP_USUAL,
        user_agent=UA_USUAL,
        geo_country="TH",
        now=now,
    )
    assert f[F_HOUR] == 3.0
    assert f[F_HOURS_FROM_TYPICAL] == pytest.approx(
        6.0
    ), "circular distance ระหว่าง 3 กับ median(9) = 6"


def test_new_device_flags_features(user_with_history, db):
    """อุปกรณ์/เบราว์เซอร์ใหม่ (Windows Chrome → iPhone Safari)."""
    now = user_with_history._base.replace(hour=USUAL_HOUR)
    f = extract_session_features(
        db,
        user_with_history.id,
        ip=IP_USUAL,
        user_agent=UA_NEW,
        geo_country="TH",
        now=now,
    )
    assert f[F_IS_NEW_DEVICE] == 1.0
    assert f[F_IS_NEW_UA_FAMILY] == 1.0


@pytest.mark.asyncio
async def test_new_country_risk_higher_than_normal(user_with_history, db):
    """ประเทศ+IP ใหม่ → คะแนนต้องสูงกว่า login ปกติ."""
    now = user_with_history._base.replace(hour=USUAL_HOUR)
    _, normal = await _score(
        db, user_with_history, ip=IP_USUAL, ua=UA_USUAL, country="TH", now=now
    )
    _, abnormal = await _score(
        db, user_with_history, ip=IP_NEW, ua=UA_USUAL, country="US", now=now
    )
    print(
        f"\n[ประเทศใหม่] ปกติ={normal['score']:.3f} → ใหม่={abnormal['score']:.3f} "
        f"decision={abnormal['decision']} {abnormal['reasons']}"
    )
    assert abnormal["score"] > normal["score"]
    # rule layer เป็น deterministic — ต้องขยับแน่นอน
    assert abnormal["breakdown"]["rule"] > normal["breakdown"]["rule"]


@pytest.mark.asyncio
async def test_unusual_time_risk_higher_than_normal(user_with_history, db):
    """เวลาผิดปกติ (ตี 3 แทน 9 โมง) → คะแนนสูงกว่า baseline."""
    base = user_with_history._base
    _, normal = await _score(
        db,
        user_with_history,
        ip=IP_USUAL,
        ua=UA_USUAL,
        country="TH",
        now=base.replace(hour=USUAL_HOUR),
    )
    _, odd_hour = await _score(
        db,
        user_with_history,
        ip=IP_USUAL,
        ua=UA_USUAL,
        country="TH",
        now=base.replace(hour=3),
    )
    print(
        f"\n[เวลาผิดปกติ] ปกติ={normal['score']:.3f} → ตี3={odd_hour['score']:.3f} "
        f"decision={odd_hour['decision']} {odd_hour['reasons']}"
    )
    assert odd_hour["score"] >= normal["score"]


@pytest.mark.asyncio
async def test_combined_anomalies_escalate(user_with_history, db):
    """รวมหลายสัญญาณ (ประเทศใหม่ + อุปกรณ์ใหม่ + เวลาผิด) → เสี่ยงสูงกว่าอันเดียว.

    หมายเหตุ: คะแนนรวมถูก cap ที่ 1.0 — ประเทศใหม่อย่างเดียวก็ชนเพดานแล้ว
    จึงเทียบที่ **breakdown แต่ละชั้น** (ยังไม่ตัน) + จำนวน reasons แทน
    """
    base = user_with_history._base
    _, one = await _score(
        db,
        user_with_history,
        ip=IP_NEW,
        ua=UA_USUAL,
        country="US",
        now=base.replace(hour=USUAL_HOUR),
    )
    _, many = await _score(
        db,
        user_with_history,
        ip=IP_NEW,
        ua=UA_NEW,
        country="US",
        now=base.replace(hour=3),
    )
    print(
        f"\n[หลายสัญญาณ] เดี่ยว={one['score']:.3f} (rule={one['breakdown']['rule']}) "
        f"→ รวม={many['score']:.3f} (rule={many['breakdown']['rule']}) "
        f"decision={many['decision']} {many['reasons']}"
    )
    assert many["score"] >= one["score"], "คะแนนรวมต้องไม่ลดลง (อาจตันที่ 1.0 ทั้งคู่)"
    # ชั้นย่อยยังไม่ตัน — ต้องขยับขึ้นจริงเมื่อมีสัญญาณมากขึ้น
    assert many["breakdown"]["rule"] > one["breakdown"]["rule"]
    assert many["breakdown"]["behavior"] > one["breakdown"]["behavior"]
    assert len(many["reasons"]) > len(one["reasons"]), "ต้องอธิบายเหตุได้มากขึ้น"


# ═════════════════════════════════════════════════════════════
# 3. Impossible travel — คนละประเทศห่างกัน 10 นาที
# ═════════════════════════════════════════════════════════════


def test_impossible_travel_10min_scores_near_max(db):
    """login ไทย → 10 นาทีต่อมา login อเมริกา = เป็นไปไม่ได้ (score ≈ 0.99)."""
    u = _mk_user(db)
    try:
        now = datetime.utcnow()
        _add_session(db, u, created_at=now - timedelta(minutes=10), country="TH")
        f = extract_session_features(
            db, u.id, ip=IP_NEW, user_agent=UA_USUAL, geo_country="US", now=now
        )
        # 1 - (10/60)/24 ≈ 0.993
        assert f[F_IMPOSSIBLE_TRAVEL] == pytest.approx(0.993, abs=0.01)
        assert f[F_IS_NEW_COUNTRY] == 1.0
    finally:
        _purge(db, u.id)


def test_impossible_travel_decays_over_time(db):
    """ประเทศเดียวกันแต่ห่าง 20 ชม. → คะแนนต่ำ (เดินทางทันจริง)."""
    u = _mk_user(db)
    try:
        now = datetime.utcnow()
        _add_session(db, u, created_at=now - timedelta(hours=20), country="TH")
        f = extract_session_features(
            db, u.id, ip=IP_NEW, user_agent=UA_USUAL, geo_country="US", now=now
        )
        # 1 - 20/24 ≈ 0.167
        assert f[F_IMPOSSIBLE_TRAVEL] == pytest.approx(0.167, abs=0.02)
    finally:
        _purge(db, u.id)


def test_same_country_no_impossible_travel(db):
    """ประเทศเดิม แม้ห่างแค่ 5 นาที → ไม่ใช่ impossible travel."""
    u = _mk_user(db)
    try:
        now = datetime.utcnow()
        _add_session(db, u, created_at=now - timedelta(minutes=5), country="TH")
        f = extract_session_features(
            db, u.id, ip=IP_USUAL, user_agent=UA_USUAL, geo_country="TH", now=now
        )
        assert f[F_IMPOSSIBLE_TRAVEL] == 0.0
    finally:
        _purge(db, u.id)


@pytest.mark.asyncio
async def test_impossible_travel_risk_higher_than_normal(user_with_history, db):
    """impossible travel → คะแนนสูงกว่า baseline อย่างชัดเจน."""
    now = datetime.utcnow()
    _, normal = await _score(
        db,
        user_with_history,
        ip=IP_USUAL,
        ua=UA_USUAL,
        country="TH",
        now=user_with_history._base.replace(hour=USUAL_HOUR),
    )
    # เพิ่ม session ไทยเมื่อ 10 นาทีที่แล้ว แล้ว login จากอเมริกา
    _add_session(
        db, user_with_history, created_at=now - timedelta(minutes=10), country="TH"
    )
    feats, travel = await _score(
        db, user_with_history, ip=IP_NEW, ua=UA_USUAL, country="US", now=now
    )
    print(
        f"\n[impossible travel] ปกติ={normal['score']:.3f} → ข้ามประเทศ 10 นาที="
        f"{travel['score']:.3f} decision={travel['decision']} {travel['reasons']}"
    )
    assert feats[F_IMPOSSIBLE_TRAVEL] > 0.9
    assert travel["score"] > normal["score"]
    assert travel["breakdown"]["rule"] > normal["breakdown"]["rule"]


@pytest.mark.asyncio
async def test_impossible_travel_triggers_reason(user_with_history, db):
    """เหตุผล (reasons) ต้องอธิบายได้ว่าเสี่ยงเพราะอะไร — ใช้โชว์ใน UI/audit."""
    now = datetime.utcnow()
    _add_session(
        db, user_with_history, created_at=now - timedelta(minutes=10), country="TH"
    )
    _, r = await _score(
        db, user_with_history, ip=IP_NEW, ua=UA_USUAL, country="US", now=now
    )
    joined = " ".join(r["reasons"]).lower()
    print(f"\n[reasons] {r['reasons']}")
    # อย่างน้อยต้องมีสัญญาณเรื่องประเทศ/การเดินทาง
    assert (
        "travel" in joined or "country" in joined
    ), f"คาดหวัง reason เกี่ยวกับ country/travel แต่ได้: {r['reasons']}"


# ═════════════════════════════════════════════════════════════
# 4. สรุปเปรียบเทียบทั้ง 3 สถานการณ์ (รันด้วย -s เพื่อดูตาราง)
# ═════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scenario_comparison_table(user_with_history, db):
    """เทียบคะแนน 3 สถานการณ์เรียงจากน้อยไปมาก: ปกติ < ประเทศใหม่ < impossible travel."""
    base = user_with_history._base
    now = datetime.utcnow()

    _, normal = await _score(
        db,
        user_with_history,
        ip=IP_USUAL,
        ua=UA_USUAL,
        country="TH",
        now=base.replace(hour=USUAL_HOUR),
    )
    _, new_country = await _score(
        db,
        user_with_history,
        ip=IP_NEW,
        ua=UA_USUAL,
        country="US",
        now=base.replace(hour=USUAL_HOUR),
    )
    _add_session(
        db, user_with_history, created_at=now - timedelta(minutes=10), country="TH"
    )
    _, travel = await _score(
        db, user_with_history, ip=IP_NEW, ua=UA_USUAL, country="US", now=now
    )

    print("\n" + "=" * 62)
    print(f"{'สถานการณ์':<28}{'score':>9}{'decision':>14}")
    print("-" * 62)
    for label, r in [
        ("1. ปกติ (ไทย/เครื่องเดิม)", normal),
        ("2. IP+ประเทศใหม่", new_country),
        ("3. ข้ามประเทศใน 10 นาที", travel),
    ]:
        print(f"{label:<28}{r['score']:>9.3f}{r['decision']:>14}")
    print("=" * 62)

    assert (
        normal["score"] <= new_country["score"] <= travel["score"]
    ), "ลำดับความเสี่ยงต้องเป็น ปกติ ≤ ประเทศใหม่ ≤ impossible travel"
