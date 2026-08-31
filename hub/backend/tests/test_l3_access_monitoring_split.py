"""L3 ต้องอยู่คนละแกนกับ access decision — บังคับด้วยเทส ไม่ใช่แค่เขียนในเอกสาร.

ที่มา (ข้อท้วงจากการรีวิวก่อนส่งผู้เชี่ยวชาญ 29 ส.ค. 2026):
เดิม L3 "ยก decision เป็น warn" แล้วเอกสารก็เขียนว่า "L3 ไม่เปลี่ยน access decision"
— สองประโยคนี้ขัดกันเอง เพราะ `warn` อยู่ใน field เดียวกับ allow/challenge/block

รอบสอง (31 ส.ค. 2026) พบว่าที่แก้ไปครอบคลุมแค่ **ครึ่งเดียวของ L3**:
sequence view แยกแกนแล้วจริง แต่ **point view (IForest 23 ฟีเจอร์) ยังบวกคะแนน
เข้า aggregate ได้ถึง +0.40** จาก threshold challenge 0.70 — ทั้งที่การทดลอง
ทุกชุดวัดผลด้วย `aggregate(rule, beh, NEUTRAL)` คือ IForest = 0
ไฟล์นี้จึงคุมทั้งสองมุมมอง ไม่ใช่เฉพาะ sequence

แยกให้ขาดเป็นสองแกน:

    access_decision     = L1/L2/L4 -> allow | challenge | block   (ตัดสินสิทธิ์ผู้ใช้)
    monitoring_decision = L3        -> normal | l3_investigate    (ธงให้ SOC ดู)

L3 **ห้ามแตะ** access_decision ทุกกรณี — รวมถึงห้ามทำ allow -> warn
(การตรวจจับที่วัดไว้ในการทดลองไม่เปลี่ยน เปลี่ยนแค่ "บันทึกผลไว้ที่ field ไหน")

Run: docker compose exec hub-backend pytest tests/test_l3_access_monitoring_split.py -v
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.security import l3_sequence as L3
from app.security.rule_engine import FEAT

ACCESS_DECISIONS = ["allow", "warn", "challenge", "block"]


def _result(**kw) -> L3.L3Result:
    base = {
        "fired": True,
        "score": 0.8,
        "tier": "extreme",
        "eligibility": "challenge",
        "n_history": 2000,
        "raw_score": 0.75,
        "percentile": 1.0,
    }
    return L3.L3Result(**{**base, "reason": L3.REASON, **kw})


def _unified(res: L3.L3Result, point_score: float = 0.0) -> dict:
    """payload รวมแบบที่ ml-service ตอบกลับ — ประกอบจาก L3Result + คะแนน point view."""
    flagged_seq = res.fired and res.eligibility in ("warn", "challenge")
    flagged_point = point_score >= 0.50
    views = (["point_iforest"] if flagged_point else []) + (
        ["sequence_residual"] if flagged_seq else []
    )
    investigate = flagged_seq or point_score >= 0.70
    return {
        "monitoring_decision": "l3_investigate" if investigate else "normal",
        "is_anomaly": bool(views),
        "unique_to_l3": bool(views),
        "detected_by": views,
        "duplicate_ratio": None,
        "duplicate_window": 0,
        "top_factors": [],
        "point": {
            "available": True,
            "anomaly_score": point_score,
            "is_anomaly": flagged_point,
            "explanation": [],
            "error": None,
        },
        "sequence": {
            "fired": res.fired,
            "score": res.score,
            "raw_score": res.raw_score,
            "percentile": res.percentile,
            "tier": res.tier,
            "eligibility": res.eligibility,
            "shadow_decision": res.shadow_decision,
            "n_history": res.n_history,
            "model_version": L3.MODEL_VERSION,
            "error": None,
        },
        "model_version": {},
        "error": None,
    }


# ── 1. API เดิมที่ผสมสองแกนต้องหายไป (กัน regression) ──────────────────────
def test_apply_channel_is_gone():
    """`apply_channel(decision, result)` เป็น API ที่ผสมสองแกนเข้าด้วยกัน — ต้องไม่มีอีก."""
    assert not hasattr(
        L3, "apply_channel"
    ), "apply_channel กลับมาแล้ว — L3 ห้ามรับ/คืนค่า access decision อีก"


def test_monitoring_vocab_is_disjoint_from_access_vocab():
    """คำศัพท์สองแกนต้องไม่ทับกันเลย — ถ้าทับ จะสับสนว่าใครเป็นคนตัดสิน."""
    monitoring = {L3.MONITORING_NORMAL, L3.MONITORING_INVESTIGATE}
    assert monitoring.isdisjoint(set(ACCESS_DECISIONS))
    assert monitoring.isdisjoint({f"would_{d}" for d in ACCESS_DECISIONS})


# ── 2. monitoring_decision ขึ้นกับ L3 เท่านั้น ไม่รับ access decision เข้ามา ──
def test_monitoring_decision_signature_takes_only_l3_result():
    """ต้องคำนวณจากผล L3 ล้วน — รับ access decision เข้ามาไม่ได้ตั้งแต่ signature."""
    import inspect

    params = list(inspect.signature(L3.monitoring_decision).parameters)
    assert params == ["result"], f"พารามิเตอร์ต้องมีแค่ result เท่านั้น (ได้ {params})"


@pytest.mark.parametrize(
    ("elig", "fired", "expected"),
    [
        ("abstain", True, L3.MONITORING_NORMAL),
        ("diagnostic", True, L3.MONITORING_NORMAL),  # log ได้ แต่ไม่ขึ้นธง
        ("warn", True, L3.MONITORING_INVESTIGATE),
        ("challenge", True, L3.MONITORING_INVESTIGATE),
        ("warn", False, L3.MONITORING_NORMAL),
        ("challenge", False, L3.MONITORING_NORMAL),
    ],
)
def test_monitoring_decision_matrix(elig, fired, expected):
    assert L3.monitoring_decision(_result(fired=fired, eligibility=elig)) == expected


# ── 3. contract ต้องแยกสองแกนให้ชัด ────────────────────────────────────────
def test_contract_exposes_monitoring_not_access():
    c = L3.to_contract(_result(), None)
    assert c["monitoring_decision"] == L3.MONITORING_INVESTIGATE
    # ห้ามมี key ที่อ่านแล้วเข้าใจว่าเป็น access decision
    assert "decision" not in c, "key ชื่อ 'decision' กำกวม — ต้องระบุว่าเป็น monitoring"
    # ค่าใน contract ต้องไม่ใช่คำในโลกของ access decision
    assert c["monitoring_decision"] not in ACCESS_DECISIONS
    # shadow_decision เก็บไว้วิเคราะห์ได้ แต่ต้องเป็น would_* ที่อ่านออกว่าไม่ enforce
    assert c["shadow_decision"] in (None, "would_warn", "would_challenge")


# ── 4. risk_engine: เปิด L3 แล้ว access decision ต้องเหมือนตอนปิดเป๊ะ ───────
async def _run(monkeypatch, *, l3_enabled: bool, fired: bool, point_score: float = 0.0):
    from app.security import risk_engine
    from app.services import l3_sequence_client as CLI

    monkeypatch.setattr(settings, "l3_sequence_enabled", l3_enabled, raising=False)
    monkeypatch.setattr(risk_engine, "get_user_profile", lambda db, uid: None)

    res = _result() if fired else _result(fired=False, tier="none")

    async def fake_l3(user_id, features, residual, access_decision="allow"):
        return _unified(res, point_score)

    # risk_engine import ฟังก์ชันนี้จากโมดูลตอนเรียก -> patch ที่โมดูลได้ตรงๆ
    monkeypatch.setattr(CLI, "evaluate_l3", fake_l3)
    monkeypatch.setattr(L3, "residual_raw", lambda *a, **kw: [0.0] * L3.DIMS)
    monkeypatch.setattr(L3, "record_residual", lambda *a, **kw: None)

    v = [0.0] * 23
    v[FEAT["permission_change_age"]] = 365.0
    return await risk_engine.evaluate_login_risk(
        v, "u-split", None, None, db=None, shadow_mode=False
    )


@pytest.mark.asyncio
async def test_access_decision_identical_with_l3_on_and_off(monkeypatch):
    """เปิด L3 แล้วยิงเต็มที่ -> access decision + reasons + score ต้องไม่ขยับเลย."""
    off = await _run(monkeypatch, l3_enabled=False, fired=False)
    on = await _run(monkeypatch, l3_enabled=True, fired=True)

    assert on["decision"] == off["decision"], "L3 เปลี่ยน access decision"
    assert on["score"] == off["score"], "L3 เปลี่ยนคะแนนความเสี่ยง"
    assert on["reasons"] == off["reasons"], "L3 แทรกเหตุผลเข้า access decision"


@pytest.mark.asyncio
@pytest.mark.parametrize("point_score", [0.0, 0.35, 0.55, 0.75, 0.99])
async def test_point_view_never_moves_access_decision(monkeypatch, point_score):
    """**หัวใจของรอบนี้** — IForest 23 ฟีเจอร์ต้องไม่ขยับ access decision ทุกระดับคะแนน.

    เดิม map_score() บวก +0.10/+0.20/+0.40 เข้า total ตามคะแนนดิบ ซึ่งที่ 0.40
    คือ 57% ของ threshold challenge (0.70) — พอที่จะพลิกผลการตัดสินได้เอง
    ทั้งที่การทดลองที่ใช้อ้างอิงวัดด้วย NEUTRAL (IForest = 0) ทั้งหมด
    """
    base = await _run(monkeypatch, l3_enabled=True, fired=False, point_score=0.0)
    out = await _run(monkeypatch, l3_enabled=True, fired=False, point_score=point_score)
    assert (
        out["decision"] == base["decision"]
    ), f"point view (score={point_score}) เปลี่ยน access decision"
    assert out["score"] == base["score"], f"point view (score={point_score}) บวกคะแนน"
    assert out["reasons"] == base["reasons"]
    # แต่ค่าดิบต้องยังถูกบันทึกไว้ — ตัดอิทธิพล ไม่ใช่ตัดข้อมูล
    assert out["breakdown"]["iforest_raw"] == point_score
    assert out["breakdown"]["iforest"] == 0.0


@pytest.mark.asyncio
async def test_point_view_reaches_monitoring_axis(monkeypatch):
    """ตัดอิทธิพลต่อ access แล้ว สัญญาณต้องไม่หาย — ต้องโผล่ที่แกน monitoring แทน."""
    out = await _run(monkeypatch, l3_enabled=True, fired=False, point_score=0.99)
    assert out["monitoring_decision"] == L3.MONITORING_INVESTIGATE
    assert "point_iforest" in out["l3"]["detected_by"]
    assert out["l3"]["is_anomaly"] is True


@pytest.mark.asyncio
async def test_l3_fires_sets_only_monitoring_field(monkeypatch):
    """L3 ยิง -> ขึ้นธงที่ monitoring_decision อย่างเดียว."""
    out = await _run(monkeypatch, l3_enabled=True, fired=True)
    assert out["monitoring_decision"] == L3.MONITORING_INVESTIGATE
    assert out["decision"] in ACCESS_DECISIONS
    assert out["breakdown"]["l3_sequence"]["monitoring_decision"] == (
        L3.MONITORING_INVESTIGATE
    )


@pytest.mark.asyncio
async def test_monitoring_normal_when_l3_quiet(monkeypatch):
    out = await _run(monkeypatch, l3_enabled=True, fired=False)
    assert out["monitoring_decision"] == L3.MONITORING_NORMAL


@pytest.mark.asyncio
async def test_monitoring_field_present_even_when_l3_disabled(monkeypatch):
    """ปิด L3 -> ยังต้องมี field (shape คงที่) และเป็น normal เสมอ."""
    out = await _run(monkeypatch, l3_enabled=False, fired=False)
    assert out["monitoring_decision"] == L3.MONITORING_NORMAL
    assert out["l3_sequence"] is None


# ── 5. คำในแกน access ต้องไม่หลุดเข้ามาทาง payload ภายนอก ──────────────────
@pytest.mark.parametrize("bad", ACCESS_DECISIONS + ["would_challenge", "mfa", ""])
def test_client_rejects_access_words_in_monitoring_field(bad):
    """ml-service ส่งคำในแกน access กลับมา -> client ต้องปัดเป็น normal.

    ป้องกันช่องทางอ้อม: ถ้าใครแก้ ml-service ให้ตอบ "challenge" มา แล้ว hub เชื่อ
    ตรงๆ ก็เท่ากับเปิดทางให้ L3 สั่ง access decision ได้อีกโดยไม่ต้องแก้ hub เลย
    """
    from app.services.l3_sequence_client import _coerce_unified

    out = _coerce_unified({"monitoring_decision": bad})
    assert out["monitoring_decision"] == "normal"


def test_client_keeps_valid_monitoring_values():
    from app.services.l3_sequence_client import _coerce_unified

    for good in ("normal", "l3_investigate"):
        assert (
            _coerce_unified({"monitoring_decision": good})["monitoring_decision"]
            == good
        )
