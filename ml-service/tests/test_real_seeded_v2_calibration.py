from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
BACKEND = Path(__file__).resolve().parents[2] / "hub" / "backend"
for path in (SCRIPTS, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.security.risk_fusion import ResolverInput  # noqa: E402
import exp_real_seeded_validation_v2 as V2  # noqa: E402
from hybrid_experiment.tune import EventRecord  # noqa: E402


def _records(*, policy_min_action=None):
    return [
        EventRecord(
            user=f"V{index % 32 + 1:02d}",
            is_attack=False,
            family=None,
            campaign=None,
            resolver=ResolverInput(
                final_score=index / 1000,
                policy_min_action=policy_min_action,
                primary_layer="rule",
            ),
        )
        for index in range(1000)
    ]


def test_calibration_uses_one_ordered_global_threshold_set():
    thresholds, detail = V2.calibrate_thresholds({(711, 20): _records()})
    assert thresholds is not None
    assert 0 <= thresholds["warn"] < thresholds["challenge"] < thresholds["block"] <= 1
    assert all(
        detail["max_point_rates"][level] <= target
        for level, target in V2.CAL_TARGETS.items()
    )


def test_calibration_stops_when_policy_floor_exceeds_normal_budget():
    thresholds, detail = V2.calibrate_thresholds(
        {(711, 20): _records(policy_min_action="challenge")}
    )
    assert thresholds is None
    assert detail["reason"] == "challenge_target_infeasible"
