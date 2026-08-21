from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_adversarial_v4.py"
SPEC = importlib.util.spec_from_file_location("adversarial_v4", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _sample():
    users = MODULE.V3.V2._load_users()
    normal = MODULE.V3.generate_normal(users, 10, 42, "normal_staggered")
    phases = MODULE.generate_attack_sequences(users, normal, 50_042, "normal_staggered")
    return users, normal, phases


def test_every_attack_is_a_four_phase_sequence():
    users, _, phases = _sample()
    eligible_lateral = sum(len(user["allowed_subsystems"]) >= 2 for user in users)
    expected_sequences = len(users) * (len(MODULE.ATTACKS) - 1) + eligible_lateral
    assert len(phases) == expected_sequences * MODULE.PHASES_PER_SEQUENCE
    grouped = {}
    for phase in phases:
        grouped.setdefault(phase.sequence_id, []).append(phase)
    assert all(len(items) == MODULE.PHASES_PER_SEQUENCE for items in grouped.values())
    assert all(sum(item.objective_phase for item in items) == 1 for items in grouped.values())


def test_stealth_phases_stay_below_rule_action_floors():
    _, _, phases = _sample()
    assert all(phase.event.failed_1h <= 2 for phase in phases)
    assert all(phase.event.success_10m <= 4 for phase in phases)
    assert all(phase.event.concurrent_sessions <= 1 for phase in phases)
    assert all(phase.event.active_subsystems <= 1 for phase in phases)
    assert all(phase.event.new_passkey == 0 for phase in phases)
    assert all(phase.event.confirmed_incident == 0 for phase in phases)


def test_attacks_reuse_trusted_platform_and_allowed_subsystems():
    users, normal, phases = _sample()
    trusted_platforms = {}
    for event in normal:
        trusted_platforms.setdefault(event.profile_id, set()).add(
            (event.device_id, event.browser_family, event.os_name)
        )
    allowed = {user["profile_id"]: set(user["allowed_subsystems"]) for user in users}
    assert all(
        (phase.event.device_id, phase.event.browser_family, phase.event.os_name)
        in trusted_platforms[phase.event.profile_id]
        for phase in phases
    )
    assert all(
        phase.event.subsystem is None
        or phase.event.subsystem in allowed[phase.event.profile_id]
        for phase in phases
    )


def test_attack_seed_is_held_out_and_deterministic():
    users = MODULE.V3.V2._load_users()
    normal = MODULE.V3.generate_normal(users, 10, 42, "normal_nat_burst")
    left = MODULE.generate_attack_sequences(users, normal, 50_042, "normal_nat_burst")
    right = MODULE.generate_attack_sequences(users, normal, 50_042, "normal_nat_burst")
    changed = MODULE.generate_attack_sequences(users, normal, 50_043, "normal_nat_burst")
    signature = lambda rows: [
        (row.sequence_id, row.event.timestamp, row.event.session_duration) for row in rows
    ]
    assert signature(left) == signature(right)
    assert signature(left) != signature(changed)


def test_shadow_flags_never_update_trusted_history():
    for decision in ("would_warn", "would_challenge", "would_block"):
        assert not MODULE.V3.is_trusted_decision(decision)
    assert MODULE.V3.is_trusted_decision("allow")
    assert MODULE.V3.is_trusted_decision("mfa_passed")


def test_representative_run_has_event_and_sequence_metrics():
    users = MODULE.V3.V2._load_users()
    stages, attacks, phases = MODULE.score_run(users, 10, 42, "normal_staggered")
    assert {row["stage"] for row in stages} == set(MODULE.STAGES)
    assert {row["attack_type"] for row in attacks} == set(MODULE.ATTACKS)
    assert {row["phase_index"] for row in phases} == {1, 2, 3, 4}
    assert all(0.0 <= row["sequence_detection_rate"] <= 1.0 for row in stages)
    assert all(0.0 <= row["preobjective_detection_rate"] <= 1.0 for row in stages)


def test_release_gate_cannot_enable_enforcement():
    users = MODULE.V3.V2._load_users()
    stages, attacks, _ = MODULE.score_run(users, 10, 42, "normal_nat_burst")
    gates = MODULE._release_gates(pd.DataFrame(stages), pd.DataFrame(attacks))
    assert gates["ready_for_enforcement"] is False
    assert "ready_for_adversarial_shadow" in gates
