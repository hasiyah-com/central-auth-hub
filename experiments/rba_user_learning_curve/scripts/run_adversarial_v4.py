#!/usr/bin/env python3
"""Adversarial V4 benchmark for stealthy, multi-stage RBA attacks.

V4 is an isolated synthetic replay.  It never writes a production model and
never enables enforcement.  Unlike the event-oriented V3 benchmark, V4 keeps
each malicious objective split into several individually weak phases and
measures whether evidence is accumulated before the objective phase.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
V3_PATH = ROOT / "scripts" / "run_production_readiness_v3.py"
RESULTS_DIR = ROOT / "results" / "adversarial_v4"

SPEC = importlib.util.spec_from_file_location("production_readiness_v3", V3_PATH)
V3 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = V3
SPEC.loader.exec_module(V3)

SIZES = V3.SIZES
SEEDS = V3.SEEDS
NORMAL_SCENARIOS = V3.NORMAL_SCENARIOS
STAGES = ("hardened_v3_event", "sequence_v4")
ATTACKS = (
    "stealth_mimicry_ato",
    "slow_credential_probe",
    "session_replay_chain",
    "gradual_exfiltration",
    "distributed_lateral_drift",
    "profile_poisoning_chain",
)
PHASES_PER_SEQUENCE = 4


@dataclass(frozen=True)
class AttackPhase:
    event: Any
    sequence_id: str
    attack_type: str
    phase_index: int
    objective_phase: bool


@dataclass
class EvidenceLedger:
    short: float = 0.0
    long: float = 0.0
    last_timestamp: Any | None = None


def _sequence_id(profile_id: str, attack_type: str, seed: int, scenario: str) -> str:
    value = f"{profile_id}|{attack_type}|{seed}|{scenario}".encode("utf-8")
    return "seq-" + hashlib.sha256(value).hexdigest()[:16]


def _normal_hour(user: dict[str, Any], phase: int) -> int:
    windows = user["normal_hours"]
    start, end = windows[phase % len(windows)]
    return int(round((int(start) + int(end)) / 2))


def generate_attack_sequences(
    users: list[dict[str, Any]], normal: list[Any], seed: int, scenario: str
) -> list[AttackPhase]:
    """Generate attacks that stay below every deterministic V3 action floor.

    All phases reuse a trusted device, UA family and OS, remain inside the
    user's subsystem permissions, and avoid hard counters.  Diversity comes
    from user-relative baselines and a seed that is separate from training.
    """
    rng = random.Random(seed * 1009 + 4049)
    by_user: dict[str, list[Any]] = defaultdict(list)
    for event in normal:
        by_user[event.profile_id].append(event)
    output: list[AttackPhase] = []

    for user_index, user in enumerate(users):
        trusted = sorted(by_user[user["profile_id"]], key=lambda e: e.timestamp)
        base = trusted[-1]
        durations = np.asarray([event.session_duration for event in trusted], dtype=float)
        duration = max(5.0, float(np.median(durations)))
        recent_gaps = [
            (right.timestamp - left.timestamp).total_seconds() / 60.0
            for left, right in zip(trusted[-9:-1], trusted[-8:])
            if right.timestamp > left.timestamp
        ]
        cadence_minutes = float(np.median(recent_gaps)) if recent_gaps else 12.0 * 60.0
        cadence_minutes = min(3.0 * 24.0 * 60.0, max(45.0, cadence_minutes))
        allowed = list(user["allowed_subsystems"])
        normal_hour = _normal_hour(user, user_index)

        for attack_index, attack_type in enumerate(ATTACKS):
            # A lateral-drift objective is only meaningful when the identity
            # legitimately has access to at least two subsystems.  Single-
            # subsystem and hub-only profiles are excluded rather than given
            # a fake cross-system event.
            if attack_type == "distributed_lateral_drift" and len(allowed) < 2:
                continue
            sequence_id = _sequence_id(user["profile_id"], attack_type, seed, scenario)
            # Each campaign is evaluated independently, so it can start at the
            # user's own observed cadence instead of an artificial fixed gap.
            # This prevents a sequence model from winning on campaign timing.
            sequence_start = base.timestamp + timedelta(minutes=cadence_minutes)
            for phase_index in range(1, PHASES_PER_SEQUENCE + 1):
                row = replace(base)
                row.split = "attack_test"
                row.attack_type = attack_type
                row.failed_1h = 0
                row.success_10m = 0
                row.concurrent_sessions = 0
                row.active_subsystems = 1 if row.subsystem else 0
                row.new_passkey = 0
                row.permission_age_hours = 9999.0
                row.confirmed_incident = 0
                row.session_duration = duration * rng.uniform(0.92, 1.08)
                row.scope_sensitivity = min(0.98, max(base.scope_sensitivity, 0.10))
                row.timestamp = sequence_start + timedelta(
                    minutes=cadence_minutes * (phase_index - 1)
                )

                if attack_type == "stealth_mimicry_ato":
                    row.success_10m = min(3, phase_index - 1)
                    row.session_duration *= (0.90, 1.00, 1.18, 1.45)[phase_index - 1]
                    row.scope_sensitivity = min(0.98, row.scope_sensitivity + 0.03 * phase_index)
                elif attack_type == "slow_credential_probe":
                    row.failed_1h = (1, 1, 2, 2)[phase_index - 1]
                    row.success_10m = 3 if phase_index == PHASES_PER_SEQUENCE else 0
                    row.timestamp += timedelta(days=phase_index * 2)
                    row.session_duration *= (1.0, 0.9, 0.75, 0.55)[phase_index - 1]
                elif attack_type == "session_replay_chain":
                    row.timestamp = sequence_start.replace(hour=normal_hour, minute=5) + timedelta(
                        minutes=(0, 7, 16, 29)[phase_index - 1]
                    )
                    row.success_10m = min(4, phase_index)
                    row.concurrent_sessions = 1 if phase_index >= 3 else 0
                    row.session_duration *= (1.0, 0.8, 0.60, 0.42)[phase_index - 1]
                elif attack_type == "gradual_exfiltration":
                    row.session_duration *= (1.20, 1.55, 2.05, 2.80)[phase_index - 1]
                    row.scope_sensitivity = min(0.98, row.scope_sensitivity + 0.06 * phase_index)
                elif attack_type == "distributed_lateral_drift":
                    if allowed:
                        row.subsystem = allowed[(phase_index + user_index) % len(allowed)]
                    row.timestamp += timedelta(hours=phase_index * 7)
                    row.scope_sensitivity = min(0.98, row.scope_sensitivity + 0.04 * phase_index)
                elif attack_type == "profile_poisoning_chain":
                    # Move gradually toward an off-profile hour and browser
                    # version without introducing a new platform identity.
                    shifted_hour = (normal_hour - 2 * (phase_index - 1)) % 24
                    row.timestamp = row.timestamp.replace(hour=shifted_hour)
                    row.browser_version += 2 * phase_index
                    row.session_duration *= (1.0, 1.10, 1.25, 1.55)[phase_index - 1]

                output.append(
                    AttackPhase(
                        event=row,
                        sequence_id=sequence_id,
                        attack_type=attack_type,
                        phase_index=phase_index,
                        objective_phase=phase_index == PHASES_PER_SEQUENCE,
                    )
                )
    return output


def _phase_evidence(row: dict[str, Any], raw: float, v3_score: float, gap_hours: float | None) -> float:
    """Convert independent weak signals into bounded sequence evidence."""
    evidence = max(0.0, v3_score - 0.32) * 0.55
    if raw >= 0.48:
        evidence += 0.08
    if row["cadence_tail_probability"] >= 0.90:
        evidence += 0.08
    if row["transition_graph_risk"] >= 0.70:
        evidence += 0.08
    if max(row["duration_log_residual"], row["cohort_duration_log_residual"]) >= 1.75:
        evidence += 0.10
    if row["failed_count_residual"] >= 1 or row["success_count_residual"] >= 2:
        evidence += 0.08
    if row["browser_version_residual"] >= 4:
        evidence += 0.07
    if gap_hours is not None and gap_hours <= 0.55:
        evidence += 0.12
    return min(0.48, evidence)


def _sequence_decision(
    row: dict[str, Any], raw: float, v3_score: float, v3_decision: str, ledger: EvidenceLedger
) -> tuple[float, str, float]:
    event = row["event"]
    gap_hours: float | None = None
    if ledger.last_timestamp is not None:
        gap_hours = max(0.0, (event.timestamp - ledger.last_timestamp).total_seconds() / 3600.0)
        ledger.short *= math.exp(-gap_hours / 30.0)
        ledger.long *= math.exp(-gap_hours / (24.0 * 14.0))
    evidence = _phase_evidence(row, raw, v3_score, gap_hours)
    ledger.short = min(1.0, ledger.short + evidence)
    ledger.long = min(1.0, ledger.long + 0.55 * evidence)
    ledger.last_timestamp = event.timestamp
    accumulated = 0.70 * ledger.short + 0.30 * ledger.long
    decision = v3_decision
    if V3.V2.ACTION_LEVEL[decision] < 2 and accumulated >= 0.60:
        decision = "challenge"
    score = max(v3_score, min(1.0, 0.20 + accumulated))
    return score, decision, accumulated


def _mimicry_distance(row: dict[str, Any]) -> float:
    """Small values mean the phase is close to its trusted user profile."""
    components = (
        row["new_device_fact"],
        row["new_ua_family_fact"],
        min(1.0, row["hour_rarity"]),
        min(1.0, row["transition_graph_risk"]),
        min(1.0, max(row["duration_log_residual"], row["cohort_duration_log_residual"]) / 4.0),
        min(1.0, row["browser_version_residual"] / 10.0),
        min(1.0, (row["failed_count_residual"] + row["success_count_residual"]) / 6.0),
    )
    return float(np.mean(components))


def _profile_poisoning_rejection(records: list[dict[str, Any]]) -> tuple[int, int]:
    """Count flagged shadow rows rejected by the canonical history allowlist."""
    flagged = [
        row for row in records
        if row["attack_type"] == "profile_poisoning_chain"
        and V3.V2.ACTION_LEVEL[row["decision"]] >= 1
    ]
    rejected = sum(not V3.is_trusted_decision("would_" + row["decision"]) for row in flagged)
    return rejected, len(flagged)


def _stage_metrics(normal: list[dict[str, Any]], attacks: list[dict[str, Any]]) -> dict[str, float]:
    detected = lambda row: V3.V2.ACTION_LEVEL[row["decision"]] >= 2
    attack_detected = sum(detected(row) for row in attacks)
    normal_fp = sum(detected(row) for row in normal)
    sequences: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in attacks:
        sequences[row["sequence_id"]].append(row)
    sequence_hits = 0
    preobjective_hits = 0
    objective_hits = 0
    times: list[int] = []
    for rows in sequences.values():
        ordered = sorted(rows, key=lambda row: row["phase_index"])
        hits = [row["phase_index"] for row in ordered if detected(row)]
        sequence_hits += bool(hits)
        preobjective_hits += any(detected(row) and not row["objective_phase"] for row in ordered)
        objective_hits += any(detected(row) and row["objective_phase"] for row in ordered)
        times.append(min(hits) if hits else PHASES_PER_SEQUENCE + 1)
    rejected, flagged = _profile_poisoning_rejection(attacks)
    return {
        "event_challenge_recall": attack_detected / max(1, len(attacks)),
        "sequence_detection_rate": sequence_hits / max(1, len(sequences)),
        "preobjective_detection_rate": preobjective_hits / max(1, len(sequences)),
        "objective_detection_rate": objective_hits / max(1, len(sequences)),
        "median_time_to_detect_phase": float(np.median(times)),
        "challenge_fpr": normal_fp / max(1, len(normal)),
        "warn_fpr": sum(V3.V2.ACTION_LEVEL[row["decision"]] >= 1 for row in normal) / max(1, len(normal)),
        "mean_attack_mimicry_distance": float(np.mean([row["mimicry_distance"] for row in attacks])),
        "flagged_poison_rejection_rate": rejected / max(1, flagged),
        "normal_count": len(normal),
        "attack_phase_count": len(attacks),
        "attack_sequence_count": len(sequences),
    }


def score_run(
    users: list[dict[str, Any]], size: int, seed: int, scenario: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    normal = V3.generate_normal(users, size, seed, scenario)
    phases = generate_attack_sequences(users, normal, seed + 50_000, scenario)
    normal_rows, attack_rows = V3.build_features(normal, [phase.event for phase in phases])
    attack_row_by_event = {id(row["event"]): row for row in attack_rows}
    train = [row for row in normal_rows if row["event"].split == "train"]
    normal_eval = [row for row in normal_rows if row["event"].split == "normal_test"]
    evaluation = normal_eval + attack_rows
    model, median, iqr = V3.V2._fit_iforest(train, seed, V3.ML_FEATURES)
    raw_values = V3.V2._raw_ml(model, median, iqr, evaluation, V3.ML_FEATURES)
    raw_by_event = {id(row["event"]): float(raw_values[index]) for index, row in enumerate(evaluation)}
    train_counts = Counter(row["event"].profile_id for row in train)

    v3_normal: list[dict[str, Any]] = []
    v4_normal: list[dict[str, Any]] = []
    ledgers: dict[str, EvidenceLedger] = defaultdict(EvidenceLedger)
    for row in sorted(normal_eval, key=lambda value: (value["event"].timestamp, value["event"].profile_id)):
        event = row["event"]
        raw = raw_by_event[id(event)]
        score, decision = V3._v3_decision(row, raw, train_counts[event.profile_id])
        base = {"decision": decision, "score": score, "label": 0, "mimicry_distance": 0.0}
        v3_normal.append(base)
        v4_score, v4_decision, _ = _sequence_decision(row, raw, score, decision, ledgers[event.profile_id])
        v4_normal.append({**base, "decision": v4_decision, "score": v4_score})

    v3_attacks: list[dict[str, Any]] = []
    v4_attacks: list[dict[str, Any]] = []
    for phase in phases:
        row = attack_row_by_event[id(phase.event)]
        raw = raw_by_event[id(phase.event)]
        score, decision = V3._v3_decision(row, raw, train_counts[phase.event.profile_id])
        base = {
            "profile_id": phase.event.profile_id,
            "sequence_id": phase.sequence_id,
            "attack_type": phase.attack_type,
            "phase_index": phase.phase_index,
            "objective_phase": phase.objective_phase,
            "decision": decision,
            "score": score,
            "raw_ml": raw,
            "label": 1,
            "mimicry_distance": _mimicry_distance(row),
            "feature_row": row,
        }
        v3_attacks.append(base)

    for sequence_id, records in _group_sequences(v3_attacks).items():
        ledger = EvidenceLedger()
        for base in sorted(records, key=lambda value: value["phase_index"]):
            row = base["feature_row"]
            score, decision, accumulated = _sequence_decision(
                row, base["raw_ml"], base["score"], base["decision"], ledger
            )
            v4_attacks.append({**base, "decision": decision, "score": score, "accumulated_evidence": accumulated})

    stage_rows = []
    for stage, normal_records, attack_records in (
        ("hardened_v3_event", v3_normal, v3_attacks),
        ("sequence_v4", v4_normal, v4_attacks),
    ):
        stage_rows.append(
            {
                "stage": stage,
                "dataset_size": size,
                "seed": seed,
                "normal_scenario": scenario,
                **_stage_metrics(normal_records, attack_records),
            }
        )

    attack_summary: list[dict[str, Any]] = []
    phase_summary: list[dict[str, Any]] = []
    for stage, records in (("hardened_v3_event", v3_attacks), ("sequence_v4", v4_attacks)):
        for attack_type in ATTACKS:
            subset = [row for row in records if row["attack_type"] == attack_type]
            metrics = _stage_metrics([], subset)
            attack_summary.append(
                {
                    "stage": stage,
                    "dataset_size": size,
                    "seed": seed,
                    "normal_scenario": scenario,
                    "attack_type": attack_type,
                    **{key: value for key, value in metrics.items() if key not in {"normal_count", "challenge_fpr", "warn_fpr"}},
                }
            )
            for phase_index in range(1, PHASES_PER_SEQUENCE + 1):
                phase_rows = [row for row in subset if row["phase_index"] == phase_index]
                phase_summary.append(
                    {
                        "stage": stage,
                        "dataset_size": size,
                        "seed": seed,
                        "normal_scenario": scenario,
                        "attack_type": attack_type,
                        "phase_index": phase_index,
                        "challenge_recall": float(np.mean([V3.V2.ACTION_LEVEL[row["decision"]] >= 2 for row in phase_rows])),
                        "mean_score": float(np.mean([row["score"] for row in phase_rows])),
                        "mean_mimicry_distance": float(np.mean([row["mimicry_distance"] for row in phase_rows])),
                    }
                )
    return stage_rows, attack_summary, phase_summary


def _group_sequences(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        grouped[row["sequence_id"]].append(row)
    return grouped


def _release_gates(stages: pd.DataFrame, attacks: pd.DataFrame) -> dict[str, Any]:
    v4 = stages[stages.stage.eq("sequence_v4")]
    cold = v4[v4.dataset_size.eq(10)]
    scenario_detection = v4.groupby("normal_scenario").sequence_detection_rate.mean()
    poisoning = attacks[
        attacks.stage.eq("sequence_v4") & attacks.attack_type.eq("profile_poisoning_chain")
    ]
    checks = {
        "challenge_fpr_le_0_003": float(v4.challenge_fpr.mean()) <= 0.003,
        "warn_fpr_le_0_01": float(v4.warn_fpr.mean()) <= 0.01,
        "sequence_detection_ge_0_90": float(v4.sequence_detection_rate.mean()) >= 0.90,
        "preobjective_detection_ge_0_70": float(v4.preobjective_detection_rate.mean()) >= 0.70,
        "median_time_to_detect_le_2": float(v4.median_time_to_detect_phase.median()) <= 2.0,
        "cold_sequence_detection_ge_0_85": float(cold.sequence_detection_rate.mean()) >= 0.85,
        "nat_detection_gap_le_0_02": float(scenario_detection.max() - scenario_detection.min()) <= 0.02,
        "flagged_poison_rejection_eq_1": float(poisoning.flagged_poison_rejection_rate.mean()) == 1.0,
        "trusted_history_allowlist": V3.TRUSTED_DECISIONS == {"allow", "mfa_passed"},
    }
    return {
        "ready_for_adversarial_shadow": all(checks.values()),
        "ready_for_enforcement": False,
        "checks": checks,
        "observed": {
            "event_challenge_recall": float(v4.event_challenge_recall.mean()),
            "sequence_detection_rate": float(v4.sequence_detection_rate.mean()),
            "preobjective_detection_rate": float(v4.preobjective_detection_rate.mean()),
            "objective_detection_rate": float(v4.objective_detection_rate.mean()),
            "median_time_to_detect_phase": float(v4.median_time_to_detect_phase.median()),
            "challenge_fpr": float(v4.challenge_fpr.mean()),
            "warn_fpr": float(v4.warn_fpr.mean()),
            "cold_sequence_detection_rate": float(cold.sequence_detection_rate.mean()),
            "nat_detection_gap": float(scenario_detection.max() - scenario_detection.min()),
            "mean_attack_mimicry_distance": float(v4.mean_attack_mimicry_distance.mean()),
            "flagged_poison_rejection_rate": float(poisoning.flagged_poison_rejection_rate.mean()),
        },
        "note": "Synthetic adversarial gates permit shadow evaluation only; production replay and canary remain mandatory.",
    }


def run_matrix(sizes: list[int], seeds: list[int], scenarios: list[str], output: Path) -> None:
    users = V3.V2._load_users()
    stages: list[dict[str, Any]] = []
    attacks: list[dict[str, Any]] = []
    phases: list[dict[str, Any]] = []
    total = len(sizes) * len(seeds) * len(scenarios)
    ordinal = 0
    for size in sizes:
        for seed in seeds:
            for scenario in scenarios:
                ordinal += 1
                print(f"[{ordinal}/{total}] n={size} seed={seed} {scenario}", flush=True)
                stage_rows, attack_rows, phase_rows = score_run(users, size, seed, scenario)
                stages.extend(stage_rows)
                attacks.extend(attack_rows)
                phases.extend(phase_rows)
    output.mkdir(parents=True, exist_ok=True)
    stage_df = pd.DataFrame(stages)
    attack_df = pd.DataFrame(attacks)
    phase_df = pd.DataFrame(phases)
    stage_df.to_csv(output / "stage_run_results.csv", index=False)
    attack_df.to_csv(output / "attack_sequence_run_results.csv", index=False)
    phase_df.to_csv(output / "phase_run_results.csv", index=False)
    stage_df.groupby(["stage", "normal_scenario", "dataset_size"], as_index=False).mean(numeric_only=True).to_csv(
        output / "stage_aggregate_results.csv", index=False
    )
    attack_df.groupby(["stage", "normal_scenario", "attack_type"], as_index=False).mean(numeric_only=True).to_csv(
        output / "attack_sequence_aggregate_results.csv", index=False
    )
    phase_df.groupby(["stage", "normal_scenario", "attack_type", "phase_index"], as_index=False).mean(numeric_only=True).to_csv(
        output / "phase_aggregate_results.csv", index=False
    )
    (output / "release_gate.json").write_text(
        json.dumps(_release_gates(stage_df, attack_df), indent=2) + "\n", encoding="utf-8"
    )
    contract = {
        "version": 4,
        "mode": "isolated_adversarial_shadow",
        "fixed_ip": "192.168.10.1",
        "geo": None,
        "train_fraction": 0.8,
        "stages": STAGES,
        "attack_sequences": ATTACKS,
        "lateral_eligibility": "at least two allowed subsystems",
        "phases_per_sequence": PHASES_PER_SEQUENCE,
        "attack_seed_offset": 50_000,
        "trusted_decisions": sorted(V3.TRUSTED_DECISIONS),
        "profile_update_policy": "only allow and mfa_passed update trusted history",
        "deterministic_floor_constraints": {
            "new_device": 0,
            "new_ua_family": 0,
            "failed_1h_max": 2,
            "success_10m_max": 4,
            "concurrent_sessions_max": 1,
            "active_subsystems_max": 1,
            "new_passkey": 0,
            "confirmed_incident": 0,
        },
    }
    (output / "adversarial_contract_v4.json").write_text(
        json.dumps(contract, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=SIZES)
    parser.add_argument("--seeds", nargs="+", type=int, default=SEEDS)
    parser.add_argument("--scenarios", nargs="+", default=NORMAL_SCENARIOS)
    parser.add_argument("--output", type=Path, default=RESULTS_DIR)
    args = parser.parse_args()
    unsupported = set(args.sizes) - set(SIZES)
    if unsupported:
        raise SystemExit(f"unsupported sizes: {sorted(unsupported)}")
    run_matrix(args.sizes, args.seeds, args.scenarios, args.output)


if __name__ == "__main__":
    main()
