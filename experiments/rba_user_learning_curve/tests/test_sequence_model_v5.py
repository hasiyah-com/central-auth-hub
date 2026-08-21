from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_sequence_model_v5.py"
SPEC = importlib.util.spec_from_file_location("sequence_model_v5", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _normal(size=10, seed=42, scenario="normal_staggered"):
    users = MODULE.V3.V2._load_users()
    return users, MODULE.V3.generate_normal(users, size, seed, scenario)


def test_sequence_features_are_derived_and_disjoint_from_event_contract():
    event_features = set(MODULE.V3.RULE_FEATURES + MODULE.V3.BEHAVIOR_FEATURES + MODULE.V3.ML_FEATURES)
    assert not (set(MODULE.SEQUENCE_FEATURES) & event_features)


def test_sequence_vector_materializes_every_contract_feature():
    _, normal = _normal()
    events = next(iter(MODULE._profile_events(normal).values()))
    row = MODULE.sequence_features(events[: MODULE.WINDOW])
    assert set(row) == set(MODULE.SEQUENCE_FEATURES)
    assert all(value == value for value in row.values())


def test_model_fit_and_thresholds_use_normal_only_windows():
    _, normal = _normal()
    model = MODULE.fit_sequence_model(normal, 42)
    assert model.fit_count > 0
    assert model.calibration_count > 0
    assert 0.0 < model.warn_threshold < model.challenge_threshold <= 1.0


def test_attack_sequences_are_not_required_to_fit_model():
    _, normal = _normal()
    left = MODULE.fit_sequence_model(normal, 42)
    right = MODULE.fit_sequence_model(normal, 42)
    assert left.warn_threshold == right.warn_threshold
    assert left.challenge_threshold == right.challenge_threshold


def test_representative_run_has_v3_v5_and_predictions():
    users = MODULE.V3.V2._load_users()
    stages, attacks, predictions = MODULE.score_run(users, 10, 42, "normal_nat_burst")
    assert {row["stage"] for row in stages} == set(MODULE.STAGES)
    assert {row["attack_type"] for row in attacks} == set(MODULE.V4.ATTACKS)
    assert {row["stage"] for row in predictions} == set(MODULE.STAGES)
    assert all(0.0 <= row["roc_auc"] <= 1.0 for row in stages)
    assert all(0.0 <= row["pr_auc"] <= 1.0 for row in stages)


def test_release_gate_never_enables_enforcement():
    users = MODULE.V3.V2._load_users()
    stages, attacks, _ = MODULE.score_run(users, 10, 42, "normal_staggered")
    gate = MODULE._release_gates(pd.DataFrame(stages), pd.DataFrame(attacks))
    assert gate["ready_for_enforcement"] is False
    assert "ready_for_system_integration_shadow" in gate


def test_admin_and_trusted_history_semantics_are_unchanged():
    assert MODULE.V3.TRUSTED_DECISIONS == {"allow", "mfa_passed"}
    users, normal = _normal()
    admins = [event for event in normal if event.user_type == "admin"]
    assert admins
    assert all(MODULE.V3.expected_normal_decision(event) == "mfa_passed" for event in admins)
