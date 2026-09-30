"""block ต้องมีหลักฐาน — คะแนนรวมที่ถึงเกณฑ์ block แต่ไม่มีกฎ hard block ยิง → challenge

ที่มา: session จริง 2026-09-29 21:36 ได้ would_block 0.95 จากพฤติกรรมอย่างเดียว
(hour_rarity + new_subsystem + scope_escalation = ชั้น 2 0.85 · ชั้น 1 มีแค่
permission_change_age +0.10) — ไม่มีหลักฐานการโจมตี เจ้าของบัญชีตัวจริงจะถูกบล็อก

กติกา: block เกิดได้เฉพาะเมื่อ Rule Engine ตั้ง `blocked=True` (IP blacklist ·
impossible travel · HARD_BLOCK_RULES) · คะแนน ≥ 0.85 ที่เหลือลดเป็น challenge
(ยังต้อง step-up — ผู้โจมตีที่ไม่มีปัจจัยที่สองผ่านไม่ได้)

รัน: docker compose exec hub-backend pytest tests/test_block_needs_evidence.py -v
"""

from __future__ import annotations

import pytest

from app.security.behavior_profiling import BehaviorResult
from app.security.iforest_scorer import IForestResult
from app.security.risk_aggregator import SCORE_BLOCK_CAPPED_REASON, aggregate
from app.security.rule_engine import RuleResult

IF_MONITOR = IForestResult(raw_score=0.39, risk_score=0.0, label="monitoring")


def _session_2026_09_29():
    rule = RuleResult(
        blocked=False, score=0.10, reasons=["permission_change_age (+0.1)"]
    )
    beh = BehaviorResult(
        score=0.85,
        reasons=[
            "hour_rarity=0.96 (+0.30)",
            "new_subsystem=x (ไม่เคยใช้, +0.30 floor=challenge)",
            "scope_escalation (+0.25)",
        ],
        min_action="challenge",
    )
    return rule, beh


def test_behavior_only_high_score_is_challenge_not_block():
    rule, beh = _session_2026_09_29()
    d = aggregate(rule, beh, IF_MONITOR, shadow_mode=False)
    assert d.decision == "challenge"
    assert d.total_score == pytest.approx(0.95)  # คะแนนยังบันทึกตามจริง


def test_shadow_mode_gives_would_challenge():
    rule, beh = _session_2026_09_29()
    d = aggregate(rule, beh, IF_MONITOR, shadow_mode=True)
    assert d.decision == "would_challenge"


def test_capped_decision_is_explained_in_reasons():
    rule, beh = _session_2026_09_29()
    d = aggregate(rule, beh, IF_MONITOR, shadow_mode=False)
    assert d.reasons[-1] == SCORE_BLOCK_CAPPED_REASON
    assert rule.reasons[0] in d.reasons and beh.reasons[0] in d.reasons


@pytest.mark.parametrize("rule_score,beh_score", [(1.0, 0.0), (0.6, 0.4), (0.0, 1.0)])
def test_any_score_mix_without_hard_block_tops_out_at_challenge(rule_score, beh_score):
    rule = RuleResult(blocked=False, score=rule_score, reasons=["x (+)"])
    beh = BehaviorResult(score=beh_score)
    d = aggregate(rule, beh, IF_MONITOR, shadow_mode=False)
    assert d.decision == "challenge"


@pytest.mark.parametrize(
    "reason",
    [
        "ip_blacklisted (203.0.113.9)",
        "failed_logins_24h=10 >= 10 (hard block)",
        "login_count_24h=50 >= 50 (hard block)",
    ],
)
def test_hard_block_evidence_still_blocks(reason):
    rule = RuleResult(blocked=True, score=1.0, reasons=[reason])
    d = aggregate(rule, BehaviorResult(score=0.0), IF_MONITOR, shadow_mode=False)
    assert d.decision == "block" and d.total_score == 1.0
    assert SCORE_BLOCK_CAPPED_REASON not in d.reasons


def test_hard_block_shadow_is_would_block():
    rule = RuleResult(blocked=True, score=1.0, reasons=["ip_blacklisted (x)"])
    d = aggregate(rule, BehaviorResult(score=0.0), IF_MONITOR, shadow_mode=True)
    assert d.decision == "would_block"


@pytest.mark.parametrize(
    "total,expected", [(0.49, "allow"), (0.50, "warn"), (0.70, "challenge")]
)
def test_lower_levels_unchanged(total, expected):
    rule = RuleResult(blocked=False, score=total)
    d = aggregate(rule, BehaviorResult(score=0.0), IF_MONITOR, shadow_mode=False)
    assert d.decision == expected
    assert SCORE_BLOCK_CAPPED_REASON not in d.reasons
