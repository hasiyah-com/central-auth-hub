"""Expert Review ต้องได้เหตุการณ์ที่ L3 มีผลต่อผลจำลอง — ขั้นที่ 10 ครึ่งหลังของแผน Hybrid Shadow.

แผนกำหนดให้ส่งเหตุการณ์เข้าเป็น alert group เมื่อ

    hybrid_shadow_decision != baseline_shadow_decision
    หรือ l3_monitoring_decision == l3_investigate

เดิม sync เลือกเฉพาะ `decision` ที่เป็น `would_*` — ในโหมด `shadow_hybrid` การตัดสินจริง
ยังเป็น L1+L2 เหตุการณ์ที่ L3 เท่านั้นเห็นจึงไม่เคยไปถึงผู้เชี่ยวชาญ และตอบคำถาม
"L3 ช่วยจริงไหม" ไม่ได้

**ที่มาของคอนฟิกต้องมาจากแถวของ login** ไม่ใช่ settings ตอน sync — ถ้าคอนฟิกเปลี่ยน
กลางหน้าต่าง กลุ่มจะถูกติดป้ายผิดโดยไม่มีอะไรฟ้อง (B66)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models import ExpertAlertGroup, LoginSession, SystemDisposition
from app.services.expert_review import grouping as G
from app.services.expert_review import sync as SY
from app.services.expert_review import views as V
from tests.test_expert_review_db import _mk_user, _purge

EXTERNAL_IP = "8.8.8.8"
BROWSER_UA = "Mozilla/5.0 shadow-selection"
EPOCH_A = {
    "shadow_epoch_id": "shadow-2026-09-17-e1",
    "risk_config_id": "hybrid-shadow-e-v1",
    "calibration_version": "hybrid-shadow-calibration-v1-synthetic",
    "calibration_sha256": "1e9038c3edfe5bed3311f46c97d67ebbe011bbfeeab8c9a710e917dfa1c5a4f0",  # pragma: allowlist secret
    "scoring_commit": "7f41fd3",
}


def _row(**over):
    base = dict(
        decision="allow",
        l3_changed_shadow_decision=None,
        risk_breakdown={},
        risk_reasons=[],
    )
    base.update(over)
    return SimpleNamespace(**base)


# ══════════════════════════════════════════════════════════════════════════════
# 1. เกณฑ์คัดเหตุการณ์ (ไม่แตะ DB)
# ══════════════════════════════════════════════════════════════════════════════


def test_actual_alert_is_still_selected():
    assert G.selection_reasons(_row(decision="would_challenge")) == {"actual_alert"}


def test_l3_changing_the_shadow_decision_is_selected():
    row = _row(l3_changed_shadow_decision=True)
    assert G.selection_reasons(row) == {"l3_changed_shadow"}


def test_l3_investigate_is_selected():
    row = _row(risk_breakdown={"l3": {"monitoring_decision": "l3_investigate"}})
    assert G.selection_reasons(row) == {"l3_investigate"}


def test_quiet_login_is_not_selected():
    row = _row(
        l3_changed_shadow_decision=False,
        risk_breakdown={"l3": {"monitoring_decision": "normal"}},
    )
    assert G.selection_reasons(row) == set()


def test_all_reasons_are_reported_together():
    row = _row(
        decision="would_warn",
        l3_changed_shadow_decision=True,
        risk_breakdown={"l3": {"monitoring_decision": "l3_investigate"}},
    )
    assert G.selection_reasons(row) == {
        "actual_alert",
        "l3_changed_shadow",
        "l3_investigate",
    }


def test_l3_only_rows_get_their_own_signal():
    """เหตุการณ์ที่ L3 เท่านั้นเห็น ต้องไม่ถูกรวมกลุ่มกับ alert จริงที่มี signal ของ L1/L2."""
    row = _row(
        l3_changed_shadow_decision=True,
        risk_breakdown={"primary_layer": "behavior"},
        risk_reasons=["hours_diff=11"],
    )
    assert G.signal_for(row) == "anomaly:l3_changed_shadow"


def test_actual_alert_keeps_existing_signal():
    row = _row(
        decision="would_challenge",
        l3_changed_shadow_decision=True,
        risk_breakdown={"primary_layer": "rule"},
        risk_reasons=["login_count_24h (+0.2)"],
    )
    assert G.signal_for(row) == "rule:login_count_24h"


def test_common_epoch_is_kept_mixed_epoch_is_dropped():
    same = [SimpleNamespace(**EPOCH_A), SimpleNamespace(**EPOCH_A)]
    assert SY.group_epoch(same) == EPOCH_A
    other = dict(EPOCH_A, risk_config_id="hybrid-shadow-e-v2")
    mixed = [SimpleNamespace(**EPOCH_A), SimpleNamespace(**other)]
    out = SY.group_epoch(mixed)
    assert out["risk_config_id"] is None, "คอนฟิกปนกันในกลุ่ม = พิสูจน์ที่มาไม่ได้"
    assert out["shadow_epoch_id"] == EPOCH_A["shadow_epoch_id"]


# ══════════════════════════════════════════════════════════════════════════════
# 2. sync บนฐานข้อมูลจริง
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def shadow_world(db):
    db.rollback()
    subject = _mk_user(db, admin=False)
    now = datetime.utcnow()
    closed = G.window_start(now - timedelta(hours=3))

    def _sess(minutes, **over):
        base = dict(
            user_id=subject.id,
            ip=EXTERNAL_IP,
            user_agent=BROWSER_UA,
            device_type="desktop",
            decision="allow",
            risk_score=0.2,
            risk_breakdown={
                "primary_layer": "behavior",
                "l3": {"monitoring_decision": "normal"},
            },
            risk_reasons=[],
            baseline_shadow_decision="would_allow",
            hybrid_shadow_decision="would_allow",
            l3_changed_shadow_decision=False,
            created_at=closed + timedelta(minutes=minutes),
            **EPOCH_A,
        )
        base.update(over)
        s = LoginSession(**base)
        db.add(s)
        return s

    l3_only = [
        _sess(
            m,
            hybrid_shadow_decision="would_challenge",
            l3_changed_shadow_decision=True,
        )
        for m in (1, 2)
    ]
    quiet = _sess(3)
    db.commit()
    yield {
        "db": db,
        "subject": subject,
        "now": now,
        "l3_only": l3_only,
        "quiet": quiet,
        "sess": _sess,
    }
    db.rollback()
    _purge(db, subject.id, [])


def _sync(w):
    return SY.sync_alert_groups(
        w["db"],
        now=w["now"],
        since=w["now"] - timedelta(hours=24),
        user_id=w["subject"].id,
    )


def _groups(w):
    return (
        w["db"]
        .query(ExpertAlertGroup)
        .filter(ExpertAlertGroup.user_id == w["subject"].id)
        .all()
    )


def test_l3_only_events_reach_expert_review(shadow_world):
    out = _sync(shadow_world)
    assert out["created"] == 1
    (g,) = _groups(shadow_world)
    assert g.primary_signal == "anomaly:l3_changed_shadow"
    assert sorted(g.session_ids) == sorted(str(s.id) for s in shadow_world["l3_only"])
    assert str(shadow_world["quiet"].id) not in g.session_ids


def test_group_epoch_comes_from_the_login_rows(shadow_world):
    _sync(shadow_world)
    (g,) = _groups(shadow_world)
    for field, value in EPOCH_A.items():
        assert getattr(g, field) == value, field
    assert g.provenance == "external"
    assert g.eligible_for_production_metrics is True


def test_rows_without_epoch_are_not_attributed_to_current_settings(
    shadow_world, monkeypatch
):
    """แถวเก่าก่อน migration ไม่มีที่มา — ห้ามเติมด้วยคอนฟิกปัจจุบันตอน sync."""
    from app.config import settings

    w = shadow_world
    monkeypatch.setattr(settings, "risk_config_id", "should-not-leak", raising=False)
    monkeypatch.setattr(settings, "scoring_commit", "should-not-leak", raising=False)
    for s in w["l3_only"]:
        for field in EPOCH_A:
            setattr(s, field, None)
    w["db"].commit()
    _sync(w)
    (g,) = _groups(w)
    assert g.risk_config_id is None
    assert g.scoring_commit is None
    assert g.eligible_for_production_metrics is False


def test_disposition_records_shadow_fields_per_event(shadow_world):
    _sync(shadow_world)
    (g,) = _groups(shadow_world)
    disp = shadow_world["db"].query(SystemDisposition).filter_by(group_id=g.id).one()
    for row in disp.model_output:
        assert row["selected_because"] == ["l3_changed_shadow"]
        assert row["baseline_shadow_decision"] == "would_allow"
        assert row["hybrid_shadow_decision"] == "would_challenge"
        assert row["l3_changed_shadow_decision"] is True
        assert row["shadow_epoch_id"] == EPOCH_A["shadow_epoch_id"]


def test_blind_payload_does_not_reveal_why_the_group_exists(shadow_world):
    """รอบ blind ต้องไม่บอกผู้ตรวจว่าระบบเลือกเหตุการณ์นี้เพราะอะไร."""
    w = shadow_world
    _sync(w)
    (g,) = _groups(w)
    payload = V.blind_payload(g, w["l3_only"], [], {})
    blob = repr(payload)
    for leak in ("l3_changed_shadow", "hybrid", "baseline", "would_", "anomaly:"):
        assert leak not in blob, leak


def test_sync_is_still_idempotent(shadow_world):
    first = _sync(shadow_world)
    second = _sync(shadow_world)
    assert first["created"] == 1
    assert second["created"] == 0
    assert second["skipped_existing"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# 3. contract ของ POST /groups/sync
# ══════════════════════════════════════════════════════════════════════════════


def test_sync_response_keeps_deprecated_epoch_alias(client, admin_token, auth_headers):
    """`epoch` เปลี่ยนชื่อเป็น `current_epoch` — คงชื่อเดิมไว้หนึ่ง release ให้ client ภายนอก.

    ค่าทั้งสองต้องเท่ากัน และต้องบอกชัดว่าเลิกใช้แล้ว · ค่านี้เป็นคอนฟิกที่รันอยู่
    ตอนนี้ **ไม่ใช่** ที่มาของกลุ่ม (ที่มาของกลุ่มอ่านจากแถว login)
    """
    r = client.post(
        "/admin/expert-review/groups/sync?since_hours=1",
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) >= {"created", "skipped_existing", "skipped_open_window"}
    assert "current_epoch" in body
    assert body["epoch"] == body["current_epoch"]
    assert "epoch" in body["deprecated"]
