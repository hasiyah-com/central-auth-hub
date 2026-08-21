from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_supervised_sequence_v6.py"
SPEC = importlib.util.spec_from_file_location("supervised_sequence_v6", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _sample():
    users = MODULE.V3.V2._load_users()
    normal = MODULE.V3.generate_normal(users, 10, 42, "normal_staggered")
    return users, normal


def test_attack_seed_partitions_are_disjoint():
    assert len({MODULE.TRAIN_ATTACK_OFFSET, MODULE.CALIBRATION_ATTACK_OFFSET, MODULE.TEST_ATTACK_OFFSET}) == 3


def test_supervised_model_records_fit_and_calibration_counts():
    users, normal = _sample()
    model = MODULE.fit_supervised_model(users, normal, 42, "normal_staggered")
    assert model.normal_fit_count > 0
    assert model.attack_fit_count > 0
    assert model.normal_calibration_count > 0
    assert model.attack_calibration_count > 0
    assert 0.0 <= model.validation_fpr <= MODULE.CALIBRATION_FPR_TARGET
    assert 0.0 <= model.challenge_threshold <= 1.0


def test_model_fit_is_deterministic():
    users, normal = _sample()
    left = MODULE.fit_supervised_model(users, normal, 42, "normal_nat_burst")
    right = MODULE.fit_supervised_model(users, normal, 42, "normal_nat_burst")
    assert np.isclose(left.challenge_threshold, right.challenge_threshold)
    assert np.isclose(left.validation_sequence_detection, right.validation_sequence_detection)


def test_representative_run_produces_v3_and_v6():
    users = MODULE.V3.V2._load_users()
    stages, attacks, predictions = MODULE.score_run(users, 10, 42, "normal_nat_burst")
    assert {row["stage"] for row in stages} == set(MODULE.STAGES)
    assert {row["attack_type"] for row in attacks} == set(MODULE.V4.ATTACKS)
    assert predictions


def test_release_gate_never_enables_enforcement():
    users = MODULE.V3.V2._load_users()
    stages, attacks, _ = MODULE.score_run(users, 10, 42, "normal_staggered")
    gate = MODULE._release_gates(pd.DataFrame(stages), pd.DataFrame(attacks))
    assert gate["ready_for_enforcement"] is False
    assert "ready_for_system_integration_shadow" in gate


def test_existing_feature_ownership_and_history_semantics_remain_intact():
    assert not (set(MODULE.V5.SEQUENCE_FEATURES) & set(MODULE.V3.RULE_FEATURES))
    assert MODULE.V3.TRUSTED_DECISIONS == {"allow", "mfa_passed"}
