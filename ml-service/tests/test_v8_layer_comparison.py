"""Single-layer arms retain production evidence and Policy Gate semantics."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
BACKEND = Path(__file__).resolve().parents[2] / "hub" / "backend"
for path in (SCRIPTS, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.security.behavior_profiling import BehaviorResult
from app.security.policy_gate import PolicyOutcome
from app.security.rule_engine import RuleResult
from exp_real_seeded_validation_v8 import V5, solo_records


def test_solo_arms_use_only_selected_layer_and_keep_policy_floor():
    ctx = V5.X.EventCtx(
        user="synthetic", is_attack=False, family=None, campaign=None,
        policy=PolicyOutcome(min_action="challenge"),
        rule=RuleResult(False, 0.9), behavior=BehaviorResult(0.2),
        l3=V5.CFG.L3Scores(point_raw=0.99),
    )
    for layer, expected in (("L1", 0.9), ("L2", 0.2)):
        record = solo_records([ctx], lambda _, score: score, layer)[0]
        assert record.resolver.final_score == expected
        assert V5.TU.resolve_rows(
            [record], {"warn": 0.4, "challenge": 0.7, "block": 0.95}
        )[0].decision == "challenge"
