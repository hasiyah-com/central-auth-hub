"""Frozen candidate semantics for aggregate-only legacy shadow replay."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from replay_l2_shadow_303 import candidate


def test_time_evidence_uses_larger_contribution_once():
    score, _, _ = candidate(
        .7, 0, 0, ["hours_diff=11.0 >= 10 (+0.40)",
                    "hour_rarity=0.98 (hour 2, +0.30)"],
    )
    assert score == .4
    score, _, _ = candidate(
        .5, 0, 0, ["hours_diff=7.0 >= 6 (+0.20)",
                    "hour_rarity=0.98 (hour 2, +0.30)"],
    )
    assert score == .3


def test_weekend_only_corroborates_independent_l2_signal():
    score, _, _ = candidate(.5, 0, 0, [
        "hours_diff=11.0 >= 10 (+0.40)", "weekend_mismatch (+0.10)",
    ])
    assert score == .4
    assert candidate(.1, 0, 0, ["weekend_mismatch (+0.10)"])[0] == 0
    assert candidate(.4, 0, 0, [
        "is_new_country (+0.30)", "weekend_mismatch (+0.10)",
    ])[0] == .4


def test_new_subsystem_floor_and_time_only_block_cap():
    reasons = ["new_subsystem=synthetic (+0.30)"]
    assert candidate(.3, 0, 0, reasons)[2] == "challenge"
    assert candidate(.95, 0, 0, [
        *reasons, "hours_diff=11.0 >= 10 (+0.40)",
        "hour_rarity=0.98 (hour 2, +0.30)",
    ])[2] == "challenge"
    assert candidate(.95, .8, 0, reasons)[2] == "block"
