#!/usr/bin/env python3
"""V6 supervised hybrid sequence detector with three-way attack isolation.

Synthetic attack campaigns used for fitting, threshold calibration, and final
evaluation use different seeds. Final test labels never select the threshold.
The V3 event scorer remains the deterministic safety layer. This runner is
isolated and can authorize shadow integration only, never enforcement.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

ROOT = Path(__file__).resolve().parents[1]
V5_PATH = ROOT / "scripts" / "run_sequence_model_v5.py"
RESULTS_DIR = ROOT / "results" / "supervised_sequence_v6"

SPEC = importlib.util.spec_from_file_location("sequence_model_v5", V5_PATH)
V5 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = V5
SPEC.loader.exec_module(V5)
V4, V3 = V5.V4, V5.V3

SIZES = V5.SIZES
SEEDS = V5.SEEDS
NORMAL_SCENARIOS = V5.NORMAL_SCENARIOS
STAGES = ("hardened_v3_event", "supervised_sequence_v6")
TRAIN_ATTACK_OFFSET = 10_000
CALIBRATION_ATTACK_OFFSET = 20_000
TEST_ATTACK_OFFSET = 50_000
NORMAL_TRAIN_SEED_OFFSETS = (100, 200, 300)
NORMAL_CALIBRATION_SEED_OFFSETS = (1_000, 2_000, 3_000)
CALIBRATION_FPR_TARGET = 0.001


@dataclass
class SupervisedSequenceModel:
    model: RandomForestClassifier
    median: np.ndarray
    iqr: np.ndarray
    challenge_threshold: float
    normal_fit_count: int
    attack_fit_count: int
    normal_calibration_count: int
    attack_calibration_count: int
    validation_fpr: float
    validation_sequence_detection: float
    validation_preobjective_detection: float


def _attack_feature_rows(normal: list[Any], phases: list[Any]) -> tuple[list[dict[str, float]], list[Any]]:
    trusted = V5._profile_events(normal)
    grouped: dict[str, list[Any]] = defaultdict(list)
    for phase in phases:
        grouped[phase.sequence_id].append(phase)
    rows: list[dict[str, float]] = []
    metadata: list[Any] = []
    for sequence in grouped.values():
        sequence.sort(key=lambda phase: phase.phase_index)
        history = list(trusted[sequence[0].event.profile_id])
        for phase in sequence:
            history.append(phase.event)
            rows.append(V5.sequence_features(history))
            metadata.append(phase)
    return rows, metadata


def _independent_normal_rows(
    users: list[dict[str, Any]], size: int, seed: int, offsets: tuple[int, ...]
) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for offset in offsets:
        for scenario in NORMAL_SCENARIOS:
            generated = V3.generate_normal(users, size, seed + offset, scenario)
            for events in V5._profile_events(generated).values():
                start = max(V5.WINDOW - 1, len(events) - 200)
                for index in range(start, len(events)):
                    rows.append(V5.sequence_features(events[: index + 1]))
    return rows


def _probabilities(
    model: RandomForestClassifier,
    median: np.ndarray,
    iqr: np.ndarray,
    rows: list[dict[str, float]],
) -> np.ndarray:
    matrix = (V5._matrix(rows) - median) / iqr
    return model.predict_proba(matrix)[:, 1]


def _validation_sequence_rates(metadata: list[Any], scores: np.ndarray, threshold: float) -> tuple[float, float]:
    grouped: dict[str, list[tuple[Any, float]]] = defaultdict(list)
    for phase, score in zip(metadata, scores):
        grouped[phase.sequence_id].append((phase, float(score)))
    detected = preobjective = 0
    for rows in grouped.values():
        hits = [(phase, score) for phase, score in rows if score >= threshold]
        detected += bool(hits)
        preobjective += any(not phase.objective_phase for phase, _ in hits)
    return detected / max(1, len(grouped)), preobjective / max(1, len(grouped))


def fit_supervised_model(
    users: list[dict[str, Any]], normal: list[Any], seed: int, scenario: str
) -> SupervisedSequenceModel:
    local_normal_fit, local_normal_calibration = V5._training_windows(normal)
    size = len(normal) // len(users)
    normal_fit = local_normal_fit + _independent_normal_rows(
        users, size, seed, NORMAL_TRAIN_SEED_OFFSETS
    )
    normal_calibration = local_normal_calibration + _independent_normal_rows(
        users, size, seed, NORMAL_CALIBRATION_SEED_OFFSETS
    )
    train_phases = V4.generate_attack_sequences(
        users, normal, seed + TRAIN_ATTACK_OFFSET, scenario
    )
    calibration_phases = V4.generate_attack_sequences(
        users, normal, seed + CALIBRATION_ATTACK_OFFSET, scenario
    )
    attack_fit, _ = _attack_feature_rows(normal, train_phases)
    attack_calibration, calibration_metadata = _attack_feature_rows(normal, calibration_phases)

    normal_matrix = V5._matrix(normal_fit)
    median = np.median(normal_matrix, axis=0)
    iqr = np.quantile(normal_matrix, 0.75, axis=0) - np.quantile(normal_matrix, 0.25, axis=0)
    iqr[iqr < 1e-6] = 1.0
    fit_rows = normal_fit + attack_fit
    labels = np.asarray([0] * len(normal_fit) + [1] * len(attack_fit), dtype=int)
    model = RandomForestClassifier(
        n_estimators=260,
        max_depth=8,
        min_samples_leaf=2,
        max_features="sqrt",
        class_weight="balanced",
        random_state=seed + 9000,
        n_jobs=-1,
    ).fit((V5._matrix(fit_rows) - median) / iqr, labels)

    normal_scores = _probabilities(model, median, iqr, normal_calibration)
    attack_scores = _probabilities(model, median, iqr, attack_calibration)
    # The decision boundary comes from independent normal-only calibration.
    # Attack validation measures generalization but cannot move the threshold.
    descending = np.sort(normal_scores)[::-1]
    allowed_false_positives = int(math.floor(CALIBRATION_FPR_TARGET * len(descending)))
    boundary_index = min(allowed_false_positives, len(descending) - 1)
    threshold = float(np.nextafter(descending[boundary_index], np.inf))
    sequence_rate, pre_rate = _validation_sequence_rates(
        calibration_metadata, attack_scores, threshold
    )
    validation_fpr = float(np.mean(normal_scores >= threshold))
    return SupervisedSequenceModel(
        model=model,
        median=median,
        iqr=iqr,
        challenge_threshold=float(threshold),
        normal_fit_count=len(normal_fit),
        attack_fit_count=len(attack_fit),
        normal_calibration_count=len(normal_calibration),
        attack_calibration_count=len(attack_calibration),
        validation_fpr=validation_fpr,
        validation_sequence_detection=float(sequence_rate),
        validation_preobjective_detection=float(pre_rate),
    )


def score_sequence(model: SupervisedSequenceModel, events: list[Any]) -> float:
    return float(
        _probabilities(
            model.model,
            model.median,
            model.iqr,
            [V5.sequence_features(events)],
        )[0]
    )


def _decision(v3_decision: str, probability: float, threshold: float) -> str:
    level = V3.V2.ACTION_LEVEL[v3_decision]
    if probability >= threshold:
        level = max(level, 2)
    return ("allow", "warn", "challenge", "block")[level]


def score_run(
    users: list[dict[str, Any]], size: int, seed: int, scenario: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    normal = V3.generate_normal(users, size, seed, scenario)
    test_phases = V4.generate_attack_sequences(
        users, normal, seed + TEST_ATTACK_OFFSET, scenario
    )
    normal_rows, attack_rows = V3.build_features(
        normal, [phase.event for phase in test_phases]
    )
    train_rows = [row for row in normal_rows if row["event"].split == "train"]
    normal_eval_rows = [row for row in normal_rows if row["event"].split == "normal_test"]
    evaluation_rows = normal_eval_rows + attack_rows
    event_model, event_median, event_iqr = V3.V2._fit_iforest(
        train_rows, seed, V3.ML_FEATURES
    )
    raw_values = V3.V2._raw_ml(
        event_model, event_median, event_iqr, evaluation_rows, V3.ML_FEATURES
    )
    row_map = {id(row["event"]): row for row in evaluation_rows}
    raw_map = {
        id(row["event"]): float(raw_values[index])
        for index, row in enumerate(evaluation_rows)
    }
    train_counts = Counter(row["event"].profile_id for row in train_rows)
    model = fit_supervised_model(users, normal, seed, scenario)

    v3_normal: list[dict[str, Any]] = []
    v6_normal: list[dict[str, Any]] = []
    normal_pending: list[tuple[dict[str, Any], dict[str, float]]] = []
    for profile_id, events in V5._profile_events(normal).items():
        history = [event for event in events if event.split == "train"]
        for event in [event for event in events if event.split == "normal_test"]:
            base = V5._base_record(
                row_map[id(event)], raw_map[id(event)], train_counts[profile_id]
            )
            v3_normal.append(base)
            history.append(event)
            normal_pending.append((base, V5.sequence_features(history)))
    normal_probabilities = _probabilities(
        model.model, model.median, model.iqr,
        [features for _, features in normal_pending],
    )
    for (base, _), probability_value in zip(normal_pending, normal_probabilities):
        probability = float(probability_value)
        v6_normal.append(
            {
                **base,
                "decision": _decision(base["decision"], probability, model.challenge_threshold),
                "anomaly_score": max(base["anomaly_score"], probability),
                "sequence_probability": probability,
            }
        )

    phase_groups: dict[str, list[Any]] = defaultdict(list)
    for phase in test_phases:
        phase_groups[phase.sequence_id].append(phase)
    trusted = V5._profile_events(normal)
    v3_attacks: list[dict[str, Any]] = []
    v6_attacks: list[dict[str, Any]] = []
    attack_pending: list[tuple[dict[str, Any], dict[str, float]]] = []
    for phases in phase_groups.values():
        phases.sort(key=lambda phase: phase.phase_index)
        profile_id = phases[0].event.profile_id
        history = list(trusted[profile_id])
        for phase in phases:
            base = V5._base_record(
                row_map[id(phase.event)],
                raw_map[id(phase.event)],
                train_counts[profile_id],
                phase,
            )
            v3_attacks.append(base)
            history.append(phase.event)
            attack_pending.append((base, V5.sequence_features(history)))
    attack_probabilities = _probabilities(
        model.model, model.median, model.iqr,
        [features for _, features in attack_pending],
    )
    for (base, _), probability_value in zip(attack_pending, attack_probabilities):
        probability = float(probability_value)
        v6_attacks.append(
            {
                **base,
                "decision": _decision(base["decision"], probability, model.challenge_threshold),
                "anomaly_score": max(base["anomaly_score"], probability),
                "sequence_probability": probability,
            }
        )

    stages: list[dict[str, Any]] = []
    attacks_out: list[dict[str, Any]] = []
    predictions: list[dict[str, Any]] = []
    for stage, normal_records, attack_records in (
        ("hardened_v3_event", v3_normal, v3_attacks),
        ("supervised_sequence_v6", v6_normal, v6_attacks),
    ):
        stages.append(
            {
                "stage": stage,
                "dataset_size": size,
                "seed": seed,
                "normal_scenario": scenario,
                "challenge_threshold": model.challenge_threshold,
                "normal_fit_count": model.normal_fit_count,
                "attack_fit_count": model.attack_fit_count,
                "normal_calibration_count": model.normal_calibration_count,
                "attack_calibration_count": model.attack_calibration_count,
                "validation_fpr": model.validation_fpr,
                "validation_sequence_detection": model.validation_sequence_detection,
                "validation_preobjective_detection": model.validation_preobjective_detection,
                **V5._metrics(normal_records, attack_records),
            }
        )
        for attack_type in V4.ATTACKS:
            subset = [row for row in attack_records if row["attack_type"] == attack_type]
            if subset:
                attacks_out.append(
                    {
                        "stage": stage,
                        "dataset_size": size,
                        "seed": seed,
                        "normal_scenario": scenario,
                        "attack_type": attack_type,
                        **{key: value for key, value in V5._metrics([], subset).items() if key not in {"challenge_fpr", "warn_fpr", "block_fpr", "normal_count"}},
                    }
                )
        for row in normal_records + attack_records:
            predictions.append(
                {
                    "stage": stage,
                    "dataset_size": size,
                    "seed": seed,
                    "normal_scenario": scenario,
                    "profile_id": row["profile_id"],
                    "sequence_id": row["sequence_id"],
                    "attack_type": row["attack_type"],
                    "phase_index": row["phase_index"],
                    "objective_phase": row["objective_phase"],
                    "label": row["label"],
                    "decision": row["decision"],
                    "anomaly_score": row["anomaly_score"],
                }
            )
    return stages, attacks_out, predictions


def _release_gates(stages: pd.DataFrame, attacks: pd.DataFrame) -> dict[str, Any]:
    v6 = stages[stages.stage.eq("supervised_sequence_v6")]
    cold = v6[v6.dataset_size.eq(10)]
    family = attacks[attacks.stage.eq("supervised_sequence_v6")].groupby("attack_type").sequence_detection_rate.mean()
    scenario = v6.groupby("normal_scenario").sequence_detection_rate.mean()
    checks = {
        "challenge_fpr_le_0_003": float(v6.challenge_fpr.mean()) <= 0.003,
        "warn_fpr_le_0_01": float(v6.warn_fpr.mean()) <= 0.01,
        "sequence_detection_ge_0_90": float(v6.sequence_detection_rate.mean()) >= 0.90,
        "minimum_attack_family_detection_ge_0_80": float(family.min()) >= 0.80,
        "preobjective_detection_ge_0_70": float(v6.preobjective_detection_rate.mean()) >= 0.70,
        "median_time_to_detect_le_2": float(v6.median_time_to_detect_phase.median()) <= 2.0,
        "cold_sequence_detection_ge_0_85": float(cold.sequence_detection_rate.mean()) >= 0.85,
        "nat_detection_gap_le_0_02": float(scenario.max() - scenario.min()) <= 0.02,
        "flagged_poison_rejection_eq_1": float(v6.flagged_poison_rejection_rate.mean()) == 1.0,
        "validation_fpr_le_0_001": float(v6.validation_fpr.mean()) <= CALIBRATION_FPR_TARGET,
    }
    return {
        "ready_for_system_integration_shadow": all(checks.values()),
        "ready_for_enforcement": False,
        "checks": checks,
        "observed": {
            "precision": float(v6.precision.mean()),
            "event_challenge_recall": float(v6.event_challenge_recall.mean()),
            "f1": float(v6.f1.mean()),
            "roc_auc": float(v6.roc_auc.mean()),
            "pr_auc": float(v6.pr_auc.mean()),
            "challenge_fpr": float(v6.challenge_fpr.mean()),
            "warn_fpr": float(v6.warn_fpr.mean()),
            "sequence_detection_rate": float(v6.sequence_detection_rate.mean()),
            "minimum_attack_family_detection": float(family.min()),
            "preobjective_detection_rate": float(v6.preobjective_detection_rate.mean()),
            "objective_detection_rate": float(v6.objective_detection_rate.mean()),
            "median_time_to_detect_phase": float(v6.median_time_to_detect_phase.median()),
            "cold_sequence_detection_rate": float(cold.sequence_detection_rate.mean()),
            "nat_detection_gap": float(scenario.max() - scenario.min()),
            "flagged_poison_rejection_rate": float(v6.flagged_poison_rejection_rate.mean()),
            "validation_fpr": float(v6.validation_fpr.mean()),
            "validation_sequence_detection": float(v6.validation_sequence_detection.mean()),
            "validation_preobjective_detection": float(v6.validation_preobjective_detection.mean()),
        },
        "note": "Passing permits isolated shadow integration only. Anonymized production replay, latency/serialization validation, monitoring, rollback, and canary are mandatory before enforcement.",
    }


def run_matrix(sizes: list[int], seeds: list[int], scenarios: list[str], output: Path) -> None:
    users = V3.V2._load_users()
    stages: list[dict[str, Any]] = []
    attacks: list[dict[str, Any]] = []
    predictions: list[dict[str, Any]] = []
    total = len(sizes) * len(seeds) * len(scenarios)
    ordinal = 0
    for size in sizes:
        for seed in seeds:
            for scenario in scenarios:
                ordinal += 1
                print(f"[{ordinal}/{total}] n={size} seed={seed} {scenario}", flush=True)
                stage_rows, attack_rows, prediction_rows = score_run(users, size, seed, scenario)
                stages.extend(stage_rows)
                attacks.extend(attack_rows)
                predictions.extend(prediction_rows)
    output.mkdir(parents=True, exist_ok=True)
    stage_df = pd.DataFrame(stages)
    attack_df = pd.DataFrame(attacks)
    prediction_df = pd.DataFrame(predictions)
    stage_df.to_csv(output / "stage_run_results.csv", index=False)
    attack_df.to_csv(output / "attack_sequence_run_results.csv", index=False)
    prediction_df.to_csv(output / "predictions.csv", index=False)
    stage_df.groupby(["stage", "normal_scenario", "dataset_size"], as_index=False).mean(numeric_only=True).to_csv(
        output / "stage_aggregate_results.csv", index=False
    )
    attack_df.groupby(["stage", "normal_scenario", "attack_type"], as_index=False).mean(numeric_only=True).to_csv(
        output / "attack_sequence_aggregate_results.csv", index=False
    )
    (output / "release_gate.json").write_text(
        json.dumps(_release_gates(stage_df, attack_df), indent=2) + "\n", encoding="utf-8"
    )
    contract = {
        "version": 6,
        "mode": "isolated_supervised_sequence_shadow",
        "fixed_ip": "192.168.10.1",
        "geo": None,
        "window_size": V5.WINDOW,
        "sequence_features": V5.SEQUENCE_FEATURES,
        "classifier": "RandomForestClassifier",
        "train_attack_seed_offset": TRAIN_ATTACK_OFFSET,
        "calibration_attack_seed_offset": CALIBRATION_ATTACK_OFFSET,
        "test_attack_seed_offset": TEST_ATTACK_OFFSET,
        "normal_calibration_seed_offsets": NORMAL_CALIBRATION_SEED_OFFSETS,
        "normal_train_seed_offsets": NORMAL_TRAIN_SEED_OFFSETS,
        "calibration_fpr_target": CALIBRATION_FPR_TARGET,
        "test_labels_select_threshold": False,
        "trusted_decisions": sorted(V3.TRUSTED_DECISIONS),
        "ready_for_enforcement": False,
    }
    (output / "sequence_contract_v6.json").write_text(
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
    run_matrix(args.sizes, args.seeds, args.scenarios, args.output)


if __name__ == "__main__":
    main()
