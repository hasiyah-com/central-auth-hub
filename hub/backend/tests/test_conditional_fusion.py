"""Conditional L3 fusion (candidate G, ระยะที่ 5) — เขียนก่อน implementation (RED).

หลักการ (ผู้ใช้กำหนด 2026-09-23):
  * L1/L2 มี policy floor รุนแรง -> คง floor
  * L1/L2 ชัดว่าเสี่ยงต่ำ -> L3 ตัวเดียวห้าม block · ยกถึง challenge ได้เฉพาะเมื่อสองมุมมองเห็นตรงกัน
    (ทั้งคู่ >= low_zone_agree) ไม่งั้นยกได้สูงสุด warn
  * L1/L2 อยู่ช่วงกำกวม -> L3 ช่วยแยก · point และ sequence มีน้ำหนักแยกกัน
  * ประวัติไม่พอ / warming / timeout / unreachable / overload -> L3 abstain · login ไม่ล้ม
  * Shadow ห้ามเปลี่ยนผลจริง · คะแนน reproducible · config ไม่รู้จัก -> ปฏิเสธ

การออกแบบที่ตรึงไว้ก่อนวัด: ขอบบนของช่วงกำกวม = `AMBIGUOUS_HIGH` (0.70 คงที่ ไม่ได้กวาด) เพื่อให้คะแนน
ไม่ขึ้นกับ threshold ที่กวาดหา FPR เท่ากัน · การจำกัดที่ warn ส่งผ่าน `ResolverInput.action_cap`
"""

from __future__ import annotations

import copy

import pytest

from app.security.evidence import Evidence, abstain
from app.security.policy_gate import PolicyOutcome
from app.security import risk_fusion as RF

THR = {"warn": 0.50, "challenge": 0.70, "block": 0.85}
GAMMA = 0.35
P = RF.ConditionalParams(
    ambiguous_low=0.40, w_point=1.0, w_sequence=0.5, low_zone_agree=0.90
)


def _ev(layer, score):
    return Evidence(layer=layer, evidence_score=score, raw_score=score)


def _l3(point=None, sequence=None):
    views = {
        k: v for k, v in (("point", point), ("sequence", sequence)) if v is not None
    }
    if not views:
        return abstain("anomaly", "insufficient_history")
    best = max(views.values())
    return Evidence(
        layer="anomaly",
        evidence_score=best,
        raw_score=best,
        detail={"views": views},
    )


def _fuse(rule, beh, l3, policy=None, params=P):
    return RF.fuse_conditional(
        policy or PolicyOutcome(),
        [_ev("rule", rule), _ev("behavior", beh), l3],
        gamma=GAMMA,
        thresholds=THR,
        params=params,
    )


def _base(rule, beh, policy=None):
    return RF.fuse(
        policy or PolicyOutcome(),
        [_ev("rule", rule), _ev("behavior", beh)],
        gamma=GAMMA,
        thresholds=THR,
    )


# ══════════════ 1–4. ความพร้อมของ L3 ══════════════


def test_1_insufficient_history_equals_baseline():
    d = _fuse(0.55, 0.10, abstain("anomaly", "insufficient_history"))
    b = _base(0.55, 0.10)
    assert (d.total_score, d.decision) == (b.total_score, b.decision)
    assert d.breakdown["conditional"]["zone"] == "l3_abstain"


def test_2_model_warming_equals_baseline():
    d = _fuse(0.60, 0.20, abstain("anomaly", "model_warming"))
    assert d.decision == _base(0.60, 0.20).decision


def test_3_point_only_in_ambiguous_zone_uses_the_point_weight():
    d = _fuse(0.55, 0.10, _l3(point=0.80))
    b = _base(0.55, 0.10).total_score
    assert d.total_score == pytest.approx(b + 1.0 * 0.80 * (1 - b), abs=1e-6)


def test_4_sequence_only_in_ambiguous_zone_uses_the_sequence_weight():
    d = _fuse(0.55, 0.10, _l3(sequence=0.80))
    b = _base(0.55, 0.10).total_score
    assert d.total_score == pytest.approx(b + 0.5 * 0.80 * (1 - b), abs=1e-6)


# ══════════════ 5–6. สองมุมมอง ══════════════


def test_5_agreeing_views_use_the_stronger_weighted_view():
    d = _fuse(0.55, 0.10, _l3(point=0.60, sequence=0.95))
    b = _base(0.55, 0.10).total_score
    a = max(1.0 * 0.60, 0.5 * 0.95)
    assert d.total_score == pytest.approx(b + a * (1 - b), abs=1e-6)


def test_6_disagreeing_views_in_low_zone_are_capped_at_warn():
    d = _fuse(0.10, 0.05, _l3(point=0.99, sequence=0.20))
    assert d.decision == "warn"
    assert d.breakdown["conditional"]["zone"] == "low"
    assert d.breakdown["resolver"]["action_cap"] == "warn"


# ══════════════ 7–9. ช่วงของ L1/L2 ══════════════


def test_7_low_zone_agreement_can_reach_challenge_but_never_block():
    d = _fuse(0.10, 0.05, _l3(point=0.99, sequence=0.97))
    assert d.decision == "challenge"


def test_7b_low_zone_never_blocks_even_at_maximum_l3():
    d = _fuse(0.0, 0.0, _l3(point=1.0, sequence=1.0))
    assert d.decision != "block"


def test_8_near_challenge_l3_can_separate():
    """ช่วงกำกวม: L1/L2 เกือบถึง challenge · L3 สูงดันข้ามได้ แต่ห้ามถึง block คนเดียว."""
    hi = _fuse(0.65, 0.20, _l3(point=0.90))
    lo = _fuse(0.65, 0.20, _l3(point=0.05))
    assert hi.decision == "challenge"
    assert lo.decision == _base(0.65, 0.20).decision
    assert hi.breakdown["conditional"]["zone"] == "ambiguous"


def test_8b_high_zone_uses_l3_only_as_corroboration():
    d = _fuse(0.80, 0.30, _l3(point=0.90))
    b = _base(0.80, 0.30).total_score
    assert d.total_score == pytest.approx(b + GAMMA * 0.90 * (1 - b), abs=1e-6)
    assert d.breakdown["conditional"]["zone"] == "high"


def test_9_policy_block_floor_is_kept():
    deny = PolicyOutcome(denied=True, reasons=["ip_blacklisted"], policy="ip_blacklist")
    d = _fuse(0.0, 0.0, _l3(point=0.0), policy=deny)
    assert d.decision == "block"


def test_9b_policy_min_action_is_kept_even_when_l3_says_normal():
    floor = PolicyOutcome(min_action="challenge", reasons=["failed_spike"])
    d = _fuse(0.05, 0.05, _l3(point=0.0, sequence=0.0), policy=floor)
    assert d.decision == "challenge"


# ══════════════ 13, 15. config และความ reproducible ══════════════


@pytest.mark.parametrize(
    "bad",
    [
        {"ambiguous_low": 0.9},  # ต้อง < AMBIGUOUS_HIGH
        {"ambiguous_low": -0.1},
        {"w_point": 1.5},
        {"w_sequence": -0.1},
        {"low_zone_agree": 1.2},
    ],
)
def test_13_invalid_params_are_refused(bad):
    kw = dict(ambiguous_low=0.40, w_point=1.0, w_sequence=0.5, low_zone_agree=0.90)
    kw.update(bad)
    with pytest.raises(ValueError):
        RF.ConditionalParams(**kw)


def test_13b_unknown_config_keys_are_refused():
    with pytest.raises(ValueError, match="gamma_boost"):
        RF.ConditionalParams.from_json(
            '{"ambiguous_low":0.4,"w_point":1,"w_sequence":0.5,'
            '"low_zone_agree":0.9,"gamma_boost":2}'
        )


def test_13c_missing_config_keys_are_refused():
    with pytest.raises(ValueError, match="low_zone_agree"):
        RF.ConditionalParams.from_json(
            '{"ambiguous_low":0.4,"w_point":1,"w_sequence":0.5}'
        )


def test_15_same_input_same_output():
    a = _fuse(0.55, 0.30, _l3(point=0.7, sequence=0.8))
    b = _fuse(0.55, 0.30, _l3(point=0.7, sequence=0.8))
    assert (a.total_score, a.decision, a.breakdown) == (
        b.total_score,
        b.decision,
        b.breakdown,
    )


def test_15b_score_does_not_depend_on_the_threshold_being_swept():
    """ต้องกวาด threshold หา FPR เท่ากันได้ด้วย resolver โดยไม่คำนวณคะแนนใหม่."""
    other = {"warn": 0.45, "challenge": 0.62, "block": 0.80}
    a = _fuse(0.55, 0.10, _l3(point=0.7, sequence=0.3))
    b = RF.fuse_conditional(
        PolicyOutcome(),
        [_ev("rule", 0.55), _ev("behavior", 0.10), _l3(point=0.7, sequence=0.3)],
        gamma=GAMMA,
        thresholds=other,
        params=P,
    )
    assert a.total_score == b.total_score
    assert a.breakdown["resolver"] == b.breakdown["resolver"]


def test_resolver_cap_round_trips():
    inp = RF.ResolverInput(final_score=0.9, action_cap="warn")
    assert RF.ResolverInput.from_dict(inp.to_dict()) == inp
    assert RF.resolve_action(inp, THR)[0] == "warn"


def test_resolver_cap_does_not_lower_a_policy_floor():
    inp = RF.ResolverInput(
        final_score=0.9, policy_min_action="challenge", action_cap="warn"
    )
    assert RF.resolve_action(inp, THR)[0] == "challenge"


def test_existing_fuse_is_unchanged_by_the_new_field():
    """B/E ใช้ fuse เดิม — field ใหม่มีค่า None ต้องไม่เปลี่ยนผลใด ๆ."""
    d = _base(0.60, 0.40)
    assert d.breakdown["resolver"].get("action_cap") is None


# ══════════════ 10–12, 14. เส้นทาง production (evaluate_login_risk) ══════════════


def _unified(**seq_over):
    from app.services.l3_sequence_client import UNIFIED_QUIET

    out = copy.deepcopy(UNIFIED_QUIET)
    out["sequence"] = {**out["sequence"], **seq_over}
    return out


async def _risk(monkeypatch, payload, params_json=P.to_json()):
    from app.config import settings
    from app.security import risk_engine
    from app.security.rule_engine import FEAT
    from app.services import l3_sequence_client as CLI

    async def fake_l3(user_id, features, residual, access_decision="allow"):
        return payload

    monkeypatch.setattr(CLI, "evaluate_l3", fake_l3)
    monkeypatch.setattr(risk_engine, "get_user_profile", lambda db, uid: None)
    monkeypatch.setattr(settings, "l3_conditional_params", params_json)
    monkeypatch.setattr(settings, "l3_mode", "shadow_hybrid")  # โหมดสาธิต (แผน 7.2)
    v = [0.0] * 23
    v[FEAT["permission_change_age"]] = 365.0
    return await risk_engine.evaluate_login_risk(
        v, "u1", ip=None, geo_country=None, db=None, subsystem_id=None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload_error", ["l3_timeout", "l3_unreachable: ConnectError"]
)
async def test_10_11_timeout_and_unreachable_abstain_without_failing(
    monkeypatch, payload_error
):
    from app.services.l3_sequence_client import UNIFIED_QUIET

    payload = {**copy.deepcopy(UNIFIED_QUIET), "error": payload_error}
    out = await _risk(monkeypatch, payload)
    cond = out["breakdown"]["conditional_shadow"]
    assert cond["zone"] == "l3_abstain"
    assert cond["decision"] == out["breakdown"]["baseline_shadow"]["decision"]


@pytest.mark.asyncio
async def test_12_per_user_overload_abstains(monkeypatch):
    out = await _risk(
        monkeypatch, _unified(eligibility="abstain", abstain_reason="per_user_overload")
    )
    assert out["breakdown"]["conditional_shadow"]["zone"] == "l3_abstain"


@pytest.mark.asyncio
async def test_14_conditional_shadow_never_changes_the_actual_decision(monkeypatch):
    with_cond = await _risk(monkeypatch, _unified(eligibility="warn", raw_score=0.99))
    without = await _risk(
        monkeypatch, _unified(eligibility="warn", raw_score=0.99), params_json=""
    )
    assert with_cond["decision"] == without["decision"]
    assert with_cond["score"] == without["score"]
    assert with_cond["baseline_shadow"] == without["baseline_shadow"]
    assert with_cond["hybrid_shadow"] == without["hybrid_shadow"]
    assert "conditional_shadow" not in without["breakdown"]


@pytest.mark.asyncio
async def test_14b_conditional_shadow_is_labelled_as_simulation(monkeypatch):
    out = await _risk(monkeypatch, _unified(eligibility="warn", raw_score=0.5))
    cond = out["breakdown"]["conditional_shadow"]
    assert cond["decision"].startswith("would_") or cond["decision"] == "allow"
    assert cond["params"] == P.to_dict()


def test_13d_settings_refuse_an_invalid_candidate_config():
    from app.config import Settings

    with pytest.raises(ValueError):
        Settings(l3_conditional_params='{"ambiguous_low": 5}')


def test_app_starts_with_conditional_params_set_in_the_environment():
    """RED ก่อนแก้: validator ใน config import risk_fusion -> policy_gate -> models -> config (วน).

    เทสเดิมไม่เจอเพราะเรียก Settings() ตอน app.config โหลดเสร็จแล้ว · ของจริงคือ process ใหม่ที่มี
    env ตั้งไว้ → ต้องรันใน subprocess เท่านั้นจึงพิสูจน์ได้ (บทเรียน B61)
    """
    import os
    import subprocess
    import sys

    env = {
        **os.environ,
        "L3_CONDITIONAL_PARAMS": (
            '{"ambiguous_low": 0.3, "low_zone_agree": 0.9, "w_point": 0.5, "w_sequence": 0.5}'
        ),
    }
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.config import settings; print(settings.l3_conditional_params)",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd="/app",
    )
    assert out.returncode == 0, out.stderr[-1500:]
    assert "ambiguous_low" in out.stdout


def test_ambiguous_high_matches_the_production_challenge_default():
    """ค่าคงที่ในโมดูลใบต้องไม่หลุดจากค่า challenge เริ่มต้นของ production."""
    from app.security.conditional_params import AMBIGUOUS_HIGH

    assert AMBIGUOUS_HIGH == RF.DEFAULT_THRESHOLDS["challenge"]
    assert RF.AMBIGUOUS_HIGH is AMBIGUOUS_HIGH


@pytest.mark.asyncio
async def test_conditional_shadow_exists_even_when_policy_denies(monkeypatch):
    """เจอตอนสาธิต VM-A06: policy ปฏิเสธ -> engine คืนค่าก่อน conditional จึงหายไปทั้งแถว.

    ต้องมีครบทุก login ไม่งั้นข้อมูล shadow อ่านไม่ออกว่า 'ไม่มีผล' หรือ 'ไม่ได้วัด' (บทเรียน B61)
    """
    from app.config import settings
    from app.security import risk_engine
    from app.security.policy_gate import PolicyOutcome
    from app.security.rule_engine import FEAT
    from app.services import l3_sequence_client as CLI

    async def fake_l3(user_id, features, residual, access_decision="allow"):
        return _unified()

    monkeypatch.setattr(CLI, "evaluate_l3", fake_l3)
    monkeypatch.setattr(risk_engine, "get_user_profile", lambda db, uid: None)
    monkeypatch.setattr(settings, "l3_conditional_params", P.to_json())
    monkeypatch.setattr(settings, "l3_mode", "shadow_hybrid")
    monkeypatch.setattr(
        risk_engine,
        "evaluate_policy",
        lambda *a, **k: PolicyOutcome(
            denied=True, reasons=["abuse_lockout"], policy="abuse"
        ),
    )
    v = [0.0] * 23
    v[FEAT["permission_change_age"]] = 365.0
    out = await risk_engine.evaluate_login_risk(
        v, "u1", ip=None, geo_country=None, db=None, subsystem_id=None
    )
    cond = out["breakdown"]["conditional_shadow"]
    assert cond["zone"] == "policy_denied"
    assert cond["decision"] == out["breakdown"]["baseline_shadow"]["decision"]
