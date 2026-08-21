from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_production_readiness_v3.py"
SPEC = importlib.util.spec_from_file_location("production_readiness_v3", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_feature_ownership_remains_disjoint():
    rule = set(MODULE.RULE_FEATURES)
    behavior = set(MODULE.BEHAVIOR_FEATURES)
    ml = set(MODULE.ML_FEATURES)
    assert not (rule & behavior)
    assert not (rule & ml)
    assert not (behavior & ml)


def test_every_contract_feature_is_materialized():
    users = MODULE.V2._load_users()
    normal = MODULE.generate_normal(users, 10, 42, "normal_staggered")
    attacks = MODULE.generate_evasive_attacks(users, normal, 42, "normal_staggered")
    normal_rows, attack_rows = MODULE.build_features(normal, attacks)
    expected = set(MODULE.RULE_FEATURES + MODULE.BEHAVIOR_FEATURES + MODULE.ML_FEATURES)
    assert normal_rows and attack_rows
    assert all(expected <= set(row) for row in normal_rows + attack_rows)


def test_trusted_history_allowlist_rejects_shadow_blocks():
    assert MODULE.is_trusted_decision("allow")
    assert MODULE.is_trusted_decision("mfa_passed")
    for decision in ("warn", "would_warn", "challenge", "would_challenge", "block", "would_block"):
        assert not MODULE.is_trusted_decision(decision)


def test_admin_normal_logins_end_with_mfa_passed():
    users = MODULE.V2._load_users()
    normal = MODULE.generate_normal(users, 10, 42, "normal_staggered")
    admins = [event for event in normal if event.user_type == "admin"]
    assert admins
    assert all(MODULE.expected_normal_decision(event) == "mfa_passed" for event in admins)


def test_evasive_security_counters_stay_below_v2_action_floors():
    users = MODULE.V2._load_users()
    normal = MODULE.generate_normal(users, 10, 42, "normal_staggered")
    attacks = MODULE.generate_evasive_attacks(users, normal, 42, "normal_staggered")
    by_type = {event.attack_type: event for event in attacks}
    assert by_type["attack_failed_near_threshold"].failed_1h == 2
    assert by_type["attack_velocity_near_threshold"].success_10m == 4
    assert by_type["attack_concurrent_near_threshold"].concurrent_sessions == 3
    assert all(event.split == "attack_test" for event in attacks)


def test_lateral_attack_has_consistent_active_session_provenance():
    users = MODULE.V2._load_users()
    normal = MODULE.generate_normal(users, 10, 42, "normal_staggered")
    attacks = MODULE.generate_known_attacks(users, normal, 10, 42, "normal_staggered")
    lateral = [event for event in attacks if event.attack_type == "attack_subsystem_lateral"]
    assert lateral
    assert all(event.active_subsystems >= 2 and event.concurrent_sessions >= 2 for event in lateral)


def test_normal_test_devices_are_already_trusted_in_train():
    users = MODULE.V2._load_users()
    normal = MODULE.generate_normal(users, 10, 45, "normal_nat_burst")
    trusted = {}
    for event in normal:
        if event.split == "train":
            trusted.setdefault(event.profile_id, set()).add(event.device_id)
    assert all(
        event.device_id in trusted[event.profile_id]
        for event in normal
        if event.split == "normal_test"
    )


def test_representative_run_reports_v2_v3_and_evasive_metrics():
    users = MODULE.V2._load_users()
    stages, attacks = MODULE.score_run(users, 10, 42, "normal_nat_burst")
    assert {row["stage"] for row in stages} == {"full_v2", "hardened_v3"}
    assert all(0.0 <= row["evasive_challenge_recall"] <= 1.0 for row in stages)
    assert {row["attack_family"] for row in attacks} == {"known", "evasive"}
    assert len(attacks) == 2 * len(MODULE.ATTACKS)


def test_release_gate_never_enables_enforcement():
    import pandas as pd

    users = MODULE.V2._load_users()
    stages, attacks = MODULE.score_run(users, 10, 42, "normal_staggered")
    gates = MODULE._release_gates(pd.DataFrame(stages), pd.DataFrame(attacks))
    assert gates["ready_for_enforcement"] is False
    assert "ready_for_production_shadow" in gates
