"""Candidate changes raw L2 evidence without mutating production behavior."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
BACKEND = Path(__file__).resolve().parents[2] / "hub" / "backend"
for path in (SCRIPTS, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.security.behavior_profiling import BehaviorResult
from exp_real_seeded_validation_v6 import adjusted


@dataclass
class Context:
    behavior: BehaviorResult


def test_correlated_time_signals_count_once_without_mutating_original():
    original = BehaviorResult(0.7, ["hours_diff=11 (+0.40)", "hour_rarity=0.98"])
    # V6's frozen condition subtracts only hour rarity when both occur.
    updated = adjusted(Context(original))
    assert round(updated.behavior.score, 2) == 0.4
    assert original.score == 0.7


def test_seen_rare_device_receives_extra_evidence_only_when_present():
    updated = adjusted(Context(BehaviorResult(0.15, ["signature_rarity=0.96"])))
    assert round(updated.behavior.score, 2) == 0.35
    unchanged = adjusted(Context(BehaviorResult(0.15, [])))
    assert unchanged.behavior.score == 0.15
