from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_feature_contract_v2.py"
SPEC = importlib.util.spec_from_file_location("feature_contract_v2", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_feature_ownership_is_disjoint():
    rule = set(MODULE.RULE_FEATURES)
    behavior = set(MODULE.BEHAVIOR_FEATURES)
    ml = set(MODULE.ML_FEATURES)
    assert not (rule & behavior)
    assert not (rule & ml)
    assert not (behavior & ml)


def test_diverse_normal_data_respects_network_and_split():
    users = MODULE._load_users()
    events = MODULE.generate_normal(users, 50, 42, "normal_nat_burst")
    assert len(events) == 12 * 50
    assert sum(event.split == "train" for event in events) == 12 * 40
    assert sum(event.split == "normal_test" for event in events) == 12 * 10
    assert len({event.timestamp.minute for event in events}) > 20
    assert len({round(event.session_duration, 1) for event in events}) > 50


def test_attacks_are_frozen_and_training_is_normal_only():
    users = MODULE._load_users()
    normal = MODULE.generate_normal(users, 10, 42, "normal_staggered")
    attacks = MODULE.generate_attacks(users, normal, 10, 42, "normal_staggered")
    assert len(attacks) == 12 * 20
    assert all(event.attack_type is None for event in normal if event.split == "train")
    assert all(event.split == "attack_test" and event.attack_type for event in attacks)


def test_policy_actions_cover_every_attack():
    assert set(MODULE.EXPECTED_ACTION) == set(MODULE.ATTACKS)
    assert MODULE.EXPECTED_ACTION["attack_combined_ato"] == "block"


def test_representative_run_has_all_stages_and_finite_metrics():
    users = MODULE._load_users()
    rows, attack_rows = MODULE.score_run(users, 10, 42, "normal_staggered")
    assert {row["stage"] for row in rows} == {
        "diverse_v1", "disjoint_v2", "full_v2", "rule_only", "behavior_only", "ml_only"
    }
    assert len(attack_rows) == 6 * len(MODULE.ATTACKS)
    for row in rows:
        assert 0.0 <= row["challenge_recall"] <= 1.0
        assert 0.0 <= row["challenge_fpr"] <= 1.0
        assert 0.0 <= row["policy_success"] <= 1.0
