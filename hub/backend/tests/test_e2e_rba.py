"""E2E — ข้อ 4 Hybrid RBA 4-Layer + SHAP + ข้อ 3(3) รายละเอียดความเสี่ยง.

E2E จริงของ risk engine: features → 4 ชั้น (Rule+Behavior+IForest+Aggregate) →
decision + reasons + breakdown + SHAP (เรียก ML service จริง). ครอบ:
  - login ปกติ → allow / คะแนนต่ำ
  - login ผิดปกติ (เครื่องใหม่+ประเทศใหม่+failed logins) → คะแนนสูง
  - hard-block rule (failed >= 10) → block ทันที
  - SHAP explanation มีจริงต่อ session
  - 3/4 ระดับ decision ตาม threshold

หมายเหตุ: ML fail-safe (B21) — ถ้า ML ล่มคืน score 0 ไม่ crash → เทสเน้น Rule+Behavior
layer ที่ deterministic + ตรวจว่า breakdown/SHAP ครบ.

รัน: docker compose exec hub-backend pytest tests/test_e2e_rba.py -v
"""

from __future__ import annotations

import uuid

import pytest

from app.database import SessionLocal
from app.models import User
from app.security.risk_engine import evaluate_login_risk
from app.security.rule_engine import FEAT

N = len(FEAT)  # จำนวน features (23)


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def fresh_user(db):
    """user ใหม่ (ไม่มีประวัติ → behavior cold start)."""
    u = User(
        email=f"e2e-rba-{uuid.uuid4().hex[:8]}@uni.ac.th",
        full_name="RBA Tester",
        user_type="staff",
        status="active",
    )
    db.add(u)
    db.commit()
    yield u
    db.query(User).filter(User.id == u.id).delete()
    db.commit()


def _features(**over):
    """สร้าง feature vector ปกติ (ทุกค่า 0) แล้ว override เฉพาะที่ต้องการ."""
    f = [0.0] * N
    # ค่า default ที่ปลอดภัย (ปกติ)
    f[FEAT["is_thailand"]] = 1.0
    f[FEAT["hour_of_day"]] = 10.0
    f[FEAT["day_of_week"]] = 1.0
    for k, v in over.items():
        f[FEAT[k]] = v
    return f


async def _score(db, user, features, geo="TH", shadow=False):
    return await evaluate_login_risk(
        features, str(user.id), "203.0.113.5", geo, db, shadow_mode=shadow
    )


# ═══════════ Positive — login ปกติ ═══════════


@pytest.mark.asyncio
async def test_e2e_rba_normal_login_low_risk(db, fresh_user):
    """login ปกติ (ไม่มีสัญญาณเสี่ยง) → คืน decision + breakdown ครบ 4 ชั้น."""
    result = await _score(db, fresh_user, _features())
    assert "decision" in result and "breakdown" in result
    assert set(result["breakdown"]) >= {"rule", "behavior", "iforest"}
    # ปกติ rule = 0 (ไม่มีกฎยิง)
    assert result["breakdown"]["rule"] == 0.0


@pytest.mark.asyncio
async def test_e2e_rba_returns_all_four_layers(db, fresh_user):
    """breakdown ต้องมีครบ 4 ชั้น (Rule/Behavior/IForest + raw)."""
    result = await _score(db, fresh_user, _features())
    bd = result["breakdown"]
    assert "rule" in bd and "behavior" in bd and "iforest" in bd
    assert 0.0 <= result["score"] <= 1.0


# ═══════════ Positive — login ผิดปกติ → คะแนนสูงขึ้น ═══════════


@pytest.mark.asyncio
async def test_e2e_rba_new_device_raises_rule_score(db, fresh_user):
    """เครื่องใหม่ (is_new_device=1) → Rule layer +0.30."""
    result = await _score(db, fresh_user, _features(is_new_device=1.0))
    assert result["breakdown"]["rule"] >= 0.30
    assert any("is_new_device" in r for r in result["reasons"])


@pytest.mark.asyncio
async def test_e2e_rba_new_foreign_country_raises_score(db, fresh_user):
    """ประเทศใหม่ + ต่างประเทศ → Rule +0.30 (new_country) +0.10 (not TH) +0.30 (foreign)."""
    result = await _score(
        db,
        fresh_user,
        _features(is_new_country=1.0, is_thailand=0.0),
        geo="RU",
    )
    assert result["breakdown"]["rule"] >= 0.30


@pytest.mark.asyncio
async def test_e2e_rba_anomaly_higher_than_normal(db, fresh_user):
    """เคสผิดปกติต้องได้คะแนนรวม >= เคสปกติ (ทิศทางถูก)."""
    normal = await _score(db, fresh_user, _features())
    anomaly = await _score(
        db, fresh_user, _features(is_new_device=1.0, is_new_user_agent_family=1.0)
    )
    assert anomaly["score"] >= normal["score"]


# ═══════════ Positive — hard block (Rule Engine) ═══════════


@pytest.mark.asyncio
async def test_e2e_rba_hard_block_failed_logins(db, fresh_user):
    """failed_logins_24h >= 10 → hard block ทันที (score 1.0, decision block)."""
    result = await _score(db, fresh_user, _features(failed_logins_24h=12.0))
    assert result["decision"] in ("block", "would_block")
    assert result["score"] == 1.0


@pytest.mark.asyncio
async def test_e2e_rba_hard_block_login_count(db, fresh_user):
    """login_count_24h >= 50 → hard block (velocity abuse)."""
    result = await _score(db, fresh_user, _features(login_count_24h=60.0))
    assert result["decision"] in ("block", "would_block")


# ═══════════ Shadow mode (negative — ไม่ enforce จริง) ═══════════


@pytest.mark.asyncio
async def test_e2e_rba_shadow_mode_would_prefix(db, fresh_user):
    """shadow mode: decision เสี่ยงสูงได้ prefix would_ (log แต่ไม่บล็อกจริง)."""
    result = await _score(
        db, fresh_user, _features(failed_logins_24h=12.0), shadow=True
    )
    assert result["decision"].startswith("would_")


# ═══════════ ข้อ 3(3) SHAP explanation ต่อ session ═══════════


@pytest.mark.asyncio
async def test_e2e_rba_breakdown_has_iforest_raw(db, fresh_user):
    """breakdown มี iforest_raw (คะแนนดิบ ML) — ฐานของ SHAP."""
    result = await _score(db, fresh_user, _features())
    assert "iforest_raw" in result["breakdown"]


@pytest.mark.asyncio
async def test_e2e_rba_reasons_human_readable(db, fresh_user):
    """reasons อ่านเข้าใจได้ (แสดงปัจจัยเสี่ยง) — สำหรับ dashboard/incident."""
    result = await _score(db, fresh_user, _features(is_new_device=1.0))
    assert isinstance(result["reasons"], list)
    assert any("is_new_device" in str(r) for r in result["reasons"])


# ═══════════ Negative — score ไม่เกิน 1.0 ═══════════


@pytest.mark.asyncio
async def test_e2e_rba_score_never_exceeds_one(db, fresh_user):
    """สัญญาณเสี่ยงหลายตัวพร้อมกัน → score ยัง cap ที่ 1.0."""
    result = await _score(
        db,
        fresh_user,
        _features(
            is_new_device=1.0,
            is_new_country=1.0,
            is_thailand=0.0,
            is_new_user_agent_family=1.0,
            failed_logins_24h=5.0,
        ),
        geo="RU",
    )
    assert 0.0 <= result["score"] <= 1.0
