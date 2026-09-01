"""สัญญาของสถาปัตยกรรม Hybrid Risk — บังคับด้วยเทส ไม่ใช่ด้วยเอกสาร.

เป้าหมายที่เทสชุดนี้คุ้มครอง:

    L1, L2 และ L3 สร้าง**หลักฐาน**ความเสี่ยง
    L4 รวมหลักฐาน สร้าง final_risk_score และตัดสินการเข้าถึง**เพียงจุดเดียว**
    Policy Gate เป็นสิ่งเดียวนอก L4 ที่มีอำนาจ เพราะเป็นข้อบังคับ ไม่ใช่การคาดการณ์

ที่มา: ก่อนหน้านี้อำนาจตัดสินกระจายอยู่หลายที่ — L1 มี `blocked`, L1/L2 มี
`min_action`, L3 เคยยก `allow -> warn` · ผลคือไม่มีจุดเดียวที่รับผิดชอบ และ
ตรวจย้อนไม่ได้ว่าใครเป็นคนตัดสิน

Run: docker compose exec hub-backend pytest tests/test_evidence_contract.py -v
"""

from __future__ import annotations

import inspect

import pytest

from app.security import risk_fusion
from app.security.evidence import (
    EVIDENCE_LEVELS,
    FORBIDDEN_IN_EVIDENCE,
    Evidence,
    abstain,
    level_of,
)
from app.security.policy_gate import PolicyOutcome
from app.security.risk_fusion import ACTIONS, fuse

THR = {"warn": 0.50, "challenge": 0.70, "block": 0.85}
GAMMA = 0.35


def _ev(layer: str, score: float, **kw) -> Evidence:
    return Evidence(layer=layer, evidence_score=score, **kw)


def _fuse(evs, policy=None, **kw):
    return fuse(
        policy or PolicyOutcome(),
        evs,
        gamma=kw.pop("gamma", GAMMA),
        thresholds=kw.pop("thresholds", THR),
        **kw,
    )


# ══════════════ 1. ชั้นหลักฐานห้ามมีคำในแกน access decision ══════════════


def test_evidence_vocabulary_is_disjoint_from_access_vocabulary():
    """คำศัพท์สองแกนต้องไม่ทับกันเลย — ถ้าทับ จะอ่านไม่ออกว่าใครเป็นคนตัดสิน."""
    assert set(EVIDENCE_LEVELS).isdisjoint(FORBIDDEN_IN_EVIDENCE)
    assert set(EVIDENCE_LEVELS).isdisjoint(set(ACTIONS))


@pytest.mark.parametrize("score", [0.0, 0.25, 0.5, 0.75, 0.99, 1.0])
def test_evidence_never_produces_an_access_word(score):
    """สแกนทุกค่าที่ Evidence ผลิตได้ — ต้องไม่มีคำในแกน access หลุดออกมา."""
    e = _ev("rule", score, reasons=["something"])
    payload = e.to_contract()
    assert payload["evidence_level"] in EVIDENCE_LEVELS
    for key in ("evidence_level", "layer"):
        assert payload[key] not in FORBIDDEN_IN_EVIDENCE


def test_evidence_dataclass_has_no_decision_field():
    """ห้ามมีฟิลด์ชื่อที่สื่อว่าเป็นการตัดสิน — กัน regression ตอนมีคนเพิ่มทีหลัง."""
    fields = set(Evidence.__dataclass_fields__)
    for bad in ("decision", "action", "blocked", "min_action", "access_decision"):
        assert bad not in fields, f"Evidence ไม่ควรมีฟิลด์ {bad}"


def test_layer_modules_do_not_import_the_aggregator():
    """ชั้นหลักฐานต้องไม่รู้จัก L4 เลย — ถ้ารู้จักแปลว่ามีทางเรียกให้ตัดสินได้."""
    import app.security.behavior_profiling as l2
    import app.security.rule_engine as l1

    for mod in (l1, l2):
        src = inspect.getsource(mod)
        assert "risk_fusion" not in src, f"{mod.__name__} ไม่ควร import L4"


# ══════════════ 2. L4 เป็นผู้ตัดสินจุดเดียว ══════════════


def test_only_fusion_produces_a_decision():
    d = _fuse([_ev("rule", 0.9)])
    assert d.decision in ACTIONS
    assert "final_risk_score" in d.breakdown


def test_no_evidence_at_all_is_allow_not_crash():
    """ทุกชั้นเงียบ -> allow · ต้องไม่ระเบิดและต้องไม่เดาว่าเสี่ยง."""
    d = _fuse([])
    assert d.decision == "allow"
    assert d.total_score == 0.0


def test_abstained_layers_are_not_counted_as_zero_risk():
    """งดออกความเห็น != ปลอดภัย — ต้องถูกบันทึกว่า abstain ไม่ใช่คะแนน 0 ที่นับได้."""
    a = abstain("anomaly", "insufficient_history")
    d = _fuse([_ev("rule", 0.9), a])
    assert "anomaly" in d.breakdown["abstained_layers"]
    # หลักฐานที่เหลือยังทำงานปกติ
    assert d.total_score == pytest.approx(0.9)


# ══════════════ 3. คุณสมบัติเชิงคณิตศาสตร์ของการรวมหลักฐาน ══════════════


@pytest.mark.parametrize("bump", [0.05, 0.2, 0.5])
def test_more_evidence_never_lowers_final_risk(bump):
    """หลักฐานสูงขึ้นแล้วความเสี่ยงรวมห้ามลด — คุณสมบัติพื้นฐานที่ต้องจริงเสมอ."""
    base = _fuse([_ev("rule", 0.4), _ev("behavior", 0.3)]).total_score
    higher = _fuse([_ev("rule", 0.4 + bump), _ev("behavior", 0.3)]).total_score
    assert higher >= base


def test_adding_a_layer_never_lowers_final_risk():
    two = _fuse([_ev("rule", 0.6), _ev("behavior", 0.2)]).total_score
    three = _fuse([_ev("rule", 0.6), _ev("behavior", 0.2), _ev("anomaly", 0.5)])
    assert three.total_score >= two


def test_fusion_is_bounded_and_never_double_counts():
    """สามชั้นเต็ม 1.0 ต้องได้ 1.0 ไม่ใช่ 3.0 — พิสูจน์ว่าไม่ได้บวกคะแนนดิบ."""
    d = _fuse([_ev("rule", 1.0), _ev("behavior", 1.0), _ev("anomaly", 1.0)])
    assert d.total_score <= 1.0
    assert d.total_score == pytest.approx(1.0)


def test_single_strong_layer_is_not_diluted_by_quiet_layers():
    """ชั้นเดียวที่เห็นชัด ต้องไม่ถูกชั้นที่เงียบเจือจาง (เหตุผลที่เลิกใช้ค่าเฉลี่ย)."""
    alone = _fuse([_ev("anomaly", 0.95)]).total_score
    with_quiet = _fuse(
        [_ev("anomaly", 0.95), _ev("rule", 0.0), _ev("behavior", 0.0)]
    ).total_score
    assert with_quiet == pytest.approx(alone)
    assert alone >= 0.95


def test_corroboration_raises_risk_above_a_single_layer():
    """สองชั้นเห็นตรงกัน ต้องได้คะแนนสูงกว่าชั้นเดียวที่แรงเท่ากัน."""
    solo = _fuse([_ev("rule", 0.8)]).total_score
    both = _fuse([_ev("rule", 0.8), _ev("behavior", 0.8)]).total_score
    assert both > solo


def test_gamma_zero_reduces_to_pure_max():
    d = _fuse([_ev("rule", 0.8), _ev("behavior", 0.7)], gamma=0.0)
    assert d.total_score == pytest.approx(0.8)


# ══════════════ 4. L3 มีผลต่อความเสี่ยงได้จริง แต่ block เดี่ยวไม่ได้ ══════════════


def test_l3_alone_can_raise_final_risk():
    """L3 ต้องมีอำนาจจริงผ่าน L4 — ไม่ใช่ monitoring-only อีกต่อไป."""
    without = _fuse([_ev("rule", 0.2), _ev("behavior", 0.1)])
    with_l3 = _fuse([_ev("rule", 0.2), _ev("behavior", 0.1), _ev("anomaly", 0.95)])
    assert with_l3.total_score > without.total_score
    assert with_l3.decision != without.decision


def test_l3_alone_must_never_block():
    """หลักฐานจาก L3 ชั้นเดียว ยกได้สูงสุดแค่ challenge."""
    d = _fuse([_ev("anomaly", 1.0), _ev("rule", 0.0), _ev("behavior", 0.0)])
    assert d.decision == "challenge"
    assert d.breakdown["solo_block_capped"] is True


def test_l3_with_corroboration_may_block():
    """มีชั้นอื่นยืนยัน -> block ได้ · ข้อจำกัดคุ้มเฉพาะกรณีชั้นเดียว."""
    d = _fuse([_ev("anomaly", 1.0), _ev("rule", 0.75)])
    assert d.decision == "block"
    assert d.breakdown["solo_block_capped"] is False


def test_rule_alone_may_block():
    """ข้อจำกัดนี้ใช้กับ L3 เท่านั้น — L1 ที่มั่นใจเต็มที่ยัง block ได้."""
    d = _fuse([_ev("rule", 1.0)])
    assert d.decision == "block"


# ══════════════ 5. Policy Gate เหนือกว่า L4 ══════════════


def test_policy_denied_blocks_regardless_of_evidence():
    d = _fuse(
        [],
        policy=PolicyOutcome(
            denied=True, reasons=["ip_denylist"], policy="ip_denylist"
        ),
    )
    assert d.decision == "block"
    assert d.total_score == 1.0
    assert d.breakdown["fusion"] == "policy_denied"


def test_policy_min_action_raises_but_never_lowers():
    """ข้อบังคับยกขึ้นได้ แต่ห้ามลดผลที่ความเสี่ยงคำนวณได้."""
    low = _fuse([_ev("rule", 0.1)], policy=PolicyOutcome(min_action="challenge"))
    assert low.decision == "challenge"

    high = _fuse([_ev("rule", 1.0)], policy=PolicyOutcome(min_action="warn"))
    assert high.decision == "block", "min_action ต้องไม่ลดผลที่แรงกว่าลงมา"


def test_shadow_mode_prefixes_every_non_allow_action():
    for score, expect in (
        (0.55, "would_warn"),
        (0.75, "would_challenge"),
        (0.95, "would_block"),
    ):
        d = _fuse([_ev("rule", score)], shadow_mode=True)
        assert d.decision == expect
    assert _fuse([_ev("rule", 0.1)], shadow_mode=True).decision == "allow"


# ══════════════ 6. Calibration ══════════════


def test_calibrated_values_stay_in_unit_range():
    from app.security.calibration import calibrate

    for layer in ("rule", "behavior", "anomaly_point", "anomaly_sequence"):
        for raw in (-5.0, 0.0, 0.37, 1.0, 99.0):
            c = calibrate(layer, raw)
            assert 0.0 <= c.value <= 1.0, f"{layer} raw={raw} -> {c.value}"


def test_uncalibrated_layers_are_reported_not_hidden():
    """ยังไม่มีตาราง calibration -> ต้องประกาศให้เห็น ไม่ใช่แอบใช้ค่าดิบเงียบๆ (B61)."""
    e = _ev("rule", 0.5)
    e.detail["calibrated"] = False
    d = _fuse([e])
    assert "rule" in d.breakdown["uncalibrated_layers"]


def test_evidence_score_is_clamped_on_construction():
    assert _ev("rule", 5.0).evidence_score == 1.0
    assert _ev("rule", -3.0).evidence_score == 0.0


@pytest.mark.parametrize(
    ("score", "expected"),
    [(0.0, "none"), (0.45, "low"), (0.7, "medium"), (0.9, "high"), (0.99, "extreme")],
)
def test_level_boundaries(score, expected):
    assert level_of(score) == expected


# ══════════════ 7. ค่าเริ่มต้นต้องถูกแทนที่ก่อนใช้จริง ══════════════


def test_defaults_are_marked_as_provisional():
    """γ และ threshold เริ่มต้นต้องมีอยู่ แต่ต้องเลือกจาก validation ก่อนใช้จริง."""
    assert 0.0 <= risk_fusion.DEFAULT_GAMMA <= 1.0
    t = risk_fusion.DEFAULT_THRESHOLDS
    assert t["warn"] < t["challenge"] < t["block"] <= 1.0


def test_solo_block_forbidden_list_covers_anomaly():
    assert "anomaly" in risk_fusion.SOLO_BLOCK_FORBIDDEN


# ══════════════ 8. L3_MODE — rollout ทีละขั้น ══════════════


async def _engine(monkeypatch, mode: str, anomaly_raw: float):
    """เรียก risk_engine จริง โดยคุมเฉพาะผลของ L3 ที่ป้อนเข้ามา."""
    from app.config import settings
    from app.security import l3_sequence as L3
    from app.security import risk_engine
    from app.services import l3_sequence_client as CLI

    monkeypatch.setattr(settings, "l3_mode", mode, raising=False)
    monkeypatch.setattr(settings, "l3_sequence_enabled", True, raising=False)
    monkeypatch.setattr(risk_engine, "get_user_profile", lambda db, uid: None)
    monkeypatch.setattr(L3, "residual_raw", lambda *a, **kw: [0.0] * L3.DIMS)
    monkeypatch.setattr(L3, "record_residual", lambda *a, **kw: None)

    async def fake_l3(
        user_id, features, residual, access_decision="allow", explain=False
    ):
        import copy

        out = copy.deepcopy(CLI.UNIFIED_QUIET)
        out["point"] = {
            "available": True,
            "anomaly_score": anomaly_raw,
            "is_anomaly": anomaly_raw >= 0.5,
            "explanation": [],
            "error": None,
            "explainer": "ready",
        }
        out["sequence"] = {**out["sequence"], "eligibility": "abstain"}
        return out

    monkeypatch.setattr(CLI, "evaluate_l3", fake_l3)

    from app.security.rule_engine import FEAT

    v = [0.0] * 23
    v[FEAT["permission_change_age"]] = 365.0
    return await risk_engine.evaluate_login_risk(
        v, "u-mode", None, None, db=None, shadow_mode=False
    )


@pytest.mark.asyncio
async def test_shadow_equals_new_fusion_without_l3(monkeypatch):
    """โหมด shadow = fusion ใหม่ที่ปิดหลักฐาน L3 — **ไม่ใช่** ระบบเดิมก่อนเปลี่ยนสถาปัตยกรรม.

    คำว่า "baseline" กำกวมจนใช้ไม่ได้ ต้องแยกสองอย่าง:
        legacy_baseline    ระบบเดิม (aggregate ผลบวก + threshold ชุดเดิม)
        new_l1_l2_baseline fusion ใหม่ (max+corroboration) ที่ปิด L3
    เทสนี้ยืนยันอย่างหลัง · อย่างแรกยืนยันด้วย Config A ในการทดลอง
    """
    off = await _engine(monkeypatch, "off", 0.0)
    shadow = await _engine(monkeypatch, "shadow", 0.99)
    assert shadow["decision"] == off["decision"]
    assert shadow["score"] == off["score"]


@pytest.mark.asyncio
async def test_l3_hybrid_stepup_lets_l3_raise_risk(monkeypatch):
    """โหมด hybrid_stepup: หลักฐาน L3 ต้องดันคะแนนขึ้นได้จริง."""
    shadow = await _engine(monkeypatch, "shadow", 0.99)
    hybrid = await _engine(monkeypatch, "hybrid_stepup", 0.99)
    assert hybrid["score"] > shadow["score"]
    cf = hybrid["breakdown"]["counterfactual"]
    assert cf["l3_changed_decision"] is True
    assert cf["l3_surfaced_new"] is True, "เดิมปล่อยผ่าน ตอนนี้ต้องถูกหยิบขึ้นมา"
    assert cf["l3_changed_score_only"] is False


@pytest.mark.asyncio
async def test_l3_hybrid_stepup_still_cannot_block_alone(monkeypatch):
    out = await _engine(monkeypatch, "hybrid_stepup", 1.0)
    assert out["decision"] != "block"


@pytest.mark.asyncio
async def test_score_change_without_decision_change_is_not_counted(monkeypatch):
    """คะแนนขยับแต่ผลเท่าเดิม ห้ามนับเป็นคุณค่าของ L3 — วัดผลจริง ไม่ใช่วัดตัวเลขขยับ."""
    out = await _engine(monkeypatch, "hybrid_stepup", 0.30)
    cf = out["breakdown"]["counterfactual"]
    if not cf["l3_changed_decision"]:
        assert cf["l3_surfaced_new"] is False


@pytest.mark.asyncio
async def test_hybrid_block_mode_does_not_exist_yet(monkeypatch):
    """ยังไม่อนุญาตให้ L3 block ได้ — โหมดที่ไม่รู้จักต้องไม่เปิดสิทธิ์เพิ่ม."""
    out = await _engine(monkeypatch, "hybrid_block", 1.0)
    assert out["decision"] != "block"


# ══════════════ 9. ECDF ต้องไม่ทำให้ค่าที่พบบ่อยกลายเป็นหลักฐานสูงสุด ══════════════


def test_ecdf_maps_the_most_common_score_to_low_evidence(tmp_path, monkeypatch):
    """login ปกติส่วนใหญ่ได้คะแนน 0.0 -> evidence ต้องต่ำ ไม่ใช่ 1.0.

    บั๊กจริงที่ smoke test จับได้ (2 ก.ย. 2569): ใช้ bisect_right ทำให้ค่าที่
    พบบ่อยที่สุดถูกนับว่า "สูงกว่าทุกคนที่เท่ากัน" -> ทุก login ปกติได้หลักฐาน 1.0
    -> block ทุกเหตุการณ์ (FPR 1.000)
    """
    import json

    from app.security import calibration as C

    # 90% ของ normal ได้ 0.0 · ที่เหลือไล่ขึ้นไป
    normals = [0.0] * 90 + [round(0.1 * i, 2) for i in range(1, 11)]
    f = tmp_path / "calibration_v1.json"
    f.write_text(
        json.dumps({"version": "test", "quantiles": {"rule": normals}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(C, "CALIBRATION_FILE", f)
    C.reload_for_tests()

    assert C.calibrate("rule", 0.0).value == pytest.approx(
        0.0
    ), "ค่าที่พบบ่อยที่สุดต้องได้หลักฐานต่ำสุด"
    assert C.calibrate("rule", 1.0).value >= 0.99, "ค่าสูงกว่าทุกคนต้องได้หลักฐานสูง"
    mid = C.calibrate("rule", 0.5).value
    assert 0.85 <= mid <= 0.99, f"ค่ากลางค่อนสูงควรอยู่ช่วงสูงแต่ไม่สุด (ได้ {mid})"
    C.reload_for_tests()
