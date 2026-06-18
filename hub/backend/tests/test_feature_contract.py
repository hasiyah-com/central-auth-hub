"""Feature contract test (B49) — single source of truth ของ feature order.

กันบั๊กคลาส "เปลี่ยน feature order แล้วลืม sync" ที่เคยทำ score มั่ว (2026-06-15):
feature order เป็น contract ข้าม 4 ไฟล์ —
  (1) ml-service/app/features.py:FEATURE_NAMES
  (2) ml-service/scripts/generate_data.py headers
  (3) hub/backend/app/services/feature_extraction.py (ลำดับ return)
  (4) hub/backend/app/security/rule_engine.py:FEAT   ← rule/behavior อ่านตาม index

ไฟล์นี้คือ source of truth ฝั่ง Hub: ถ้าใครแก้ feature order ที่ไหน
ต้องอัปเดต CANONICAL นี้ → test ที่พึ่ง FEAT/extraction จะ fail ทันทีถ้าไม่ตรง

หมายเหตุ: ฝั่ง ml-service (features.py/generate_data) อยู่คนละ container —
import ตรงไม่ได้ → ต้องตรงกับ CANONICAL นี้ด้วยมือ (B49)
"""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.database import SessionLocal

# ── Single source of truth (22 features) — ต้องตรงกับ ml-service/app/features.py ──
CANONICAL_FEATURES = [
    "hour_of_day",
    "day_of_week",
    "hours_from_typical_login_time",
    "is_thailand",
    "is_new_country",
    "country_change_count_30d",
    "is_new_device",
    "is_new_user_agent_family",
    "log_minutes_since_last_login",
    "login_count_24h",
    "failed_logins_24h",
    "passkey_count",
    "passkey_age_days",
    "new_passkey_recently_added",
    "passkey_last_used_days",
    "concurrent_session_count",
    "active_subsystem_count",
    "weekday_usage_score",
    "scope_sensitivity_score",
    "ever_changed_permission",
    "permission_change_age",
    "confirmed_incident_count",
    "impossible_travel_score",
]
FEATURE_COUNT = len(CANONICAL_FEATURES)  # 23


@pytest.fixture
def db() -> Session:
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.mark.smoke
def test_canonical_count_is_23():
    assert FEATURE_COUNT == 23
    assert len(set(CANONICAL_FEATURES)) == 23  # ไม่มีชื่อซ้ำ
    assert "is_weekend" not in CANONICAL_FEATURES  # ตัดแล้ว
    assert "has_passkey" not in CANONICAL_FEATURES  # ตัดแล้ว


@pytest.mark.smoke
def test_rule_engine_feat_matches_canonical():
    """rule_engine.FEAT (index map) ต้องตรงกับ CANONICAL ทั้งชื่อ + ลำดับ."""
    from app.security.rule_engine import FEAT

    # ชื่อเรียงตาม index ต้อง == CANONICAL
    names_in_index_order = [
        name for name, _ in sorted(FEAT.items(), key=lambda kv: kv[1])
    ]
    assert (
        names_in_index_order == CANONICAL_FEATURES
    ), "rule_engine.FEAT ไม่ตรง CANONICAL — เปลี่ยน feature order แล้วลืม sync FEAT (B49)"
    # index ต้อง 0..21 ครบ unique
    assert sorted(FEAT.values()) == list(range(FEATURE_COUNT))


@pytest.mark.smoke
def test_feature_extraction_returns_canonical_count(db):
    """feature_extraction ต้องคืนจำนวนตรง CANONICAL (เรียก cold-start user — ไม่ต้อง seed)."""
    from app.services.feature_extraction import extract_session_features

    feats = extract_session_features(db, uuid.uuid4(), None, None, None)
    assert (
        len(feats) == FEATURE_COUNT
    ), f"extract คืน {len(feats)} ตัว แต่ contract = {FEATURE_COUNT} (B49)"
