#!/usr/bin/env python3
"""V5 normal-only sequence model for RBA shadow integration.

The model is trained and calibrated only with trusted normal sequences. Attack
campaigns are generated with held-out seeds and are never used to choose the
decision thresholds. V5 remains isolated from the production request path and
can only pass a shadow-integration gate; enforcement is always disabled.
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
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
V4_PATH = ROOT / "scripts" / "run_adversarial_v4.py"
RESULTS_DIR = ROOT / "results" / "sequence_model_v5"

SPEC = importlib.util.spec_from_file_location("adversarial_v4", V4_PATH)
V4 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = V4
SPEC.loader.exec_module(V4)
V3 = V4.V3

SIZES = V4.SIZES
SEEDS = V4.SEEDS
NORMAL_SCENARIOS = V4.NORMAL_SCENARIOS
STAGES = ("hardened_v3_event", "sequence_model_v5")
WINDOW = 4
SEQUENCE_FEATURES = (
    "gap_log_mean",
    "gap_log_range",
    "rapid_gap_count",
    "failed_sum",
    "success_sum",
    "concurrent_sum",
    "duration_log_slope",
    "duration_log_range",
    "scope_slope",
    "scope_duration_growth",
    "browser_version_slope",
    "subsystem_switch_rate",
    "hour_circular_spread",
)


@dataclass
class SequenceModel:
    model: IsolationForest
    median: np.ndarray
    iqr: np.ndarray
    residual_center: float
    residual_scale: float
    warn_threshold: float
    challenge_threshold: float
    fit_count: int
    calibration_count: int


def _linear_slope(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    x = np.arange(len(values), dtype=float)
    return float(np.polyfit(x, np.asarray(values, dtype=float), 1)[0])


def sequence_features(events: list[Any]) -> dict[str, float]:
    if len(events) < WINDOW:
        raise ValueError(f"sequence requires at least {WINDOW} events")
    items = sorted(events[-WINDOW:], key=lambda event: event.timestamp)
    gaps = [
        max(0.5, (right.timestamp - left.timestamp).total_seconds() / 60.0)
        for left, right in zip(items, items[1:])
    ]
    gap_logs = [math.log1p(value) for value in gaps]
    duration_logs = [math.log1p(max(0.0, event.session_duration)) for event in items]
    scopes = [float(event.scope_sensitivity) for event in items]
    versions = [float(event.browser_version) for event in items]
    angles = np.asarray([2.0 * math.pi * event.timestamp.hour / 24.0 for event in items])
    resultant = abs(np.mean(np.exp(1j * angles)))
    circular_spread = 1.0 - float(resultant)
    switches = sum(
        left.subsystem != right.subsystem for left, right in zip(items, items[1:])
    )
    return {
        "gap_log_mean": float(np.mean(gap_logs)),
        "gap_log_range": float(max(gap_logs) - min(gap_logs)),
        "rapid_gap_count": float(sum(value <= 35.0 for value in gaps)),
        "failed_sum": float(sum(event.failed_1h for event in items)),
        "success_sum": float(sum(event.success_10m for event in items)),
        "concurrent_sum": float(sum(event.concurrent_sessions for event in items)),
        "duration_log_slope": _linear_slope(duration_logs),
        "duration_log_range": float(max(duration_logs) - min(duration_logs)),
        "scope_slope": _linear_slope(scopes),
        "scope_duration_growth": float(
            max(0.0, duration_logs[-1] - duration_logs[0])
            * max(scopes[-1], float(np.mean(scopes)))
        ),
        "browser_version_slope": _linear_slope(versions),
        "subsystem_switch_rate": switches / max(1.0, len(items) - 1.0),
        "hour_circular_spread": circular_spread,
    }


def _profile_events(events: list[Any]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for event in events:
        grouped[event.profile_id].append(event)
    for profile_id in grouped:
        grouped[profile_id].sort(key=lambda event: event.timestamp)
    return grouped


def _training_windows(normal: list[Any]) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    fit: list[dict[str, float]] = []
    calibration: list[dict[str, float]] = []
    for events in _profile_events([event for event in normal if event.split == "train"]).values():
        cut = max(WINDOW, int(len(events) * 0.75))
        for index in range(WINDOW - 1, len(events)):
            row = sequence_features(events[: index + 1])
            (fit if index < cut else calibration).append(row)
    if not calibration:
        calibration = fit[-max(1, len(fit) // 5):]
        fit = fit[: -len(calibration)] or fit
    return fit, calibration


def _matrix(rows: list[dict[str, float]]) -> np.ndarray:
    return np.asarray([[row[name] for name in SEQUENCE_FEATURES] for row in rows], dtype=float)


def _base_scores(
    model: IsolationForest,
    median: np.ndarray,
    iqr: np.ndarray,
    residual_center: float,
    residual_scale: float,
    rows: list[dict[str, float]],
) -> np.ndarray:
    scaled = (_matrix(rows) - median) / iqr
    if_component = 1.0 / (1.0 + np.exp(model.decision_function(scaled) * 7.0))
    max_residual = np.max(np.abs(scaled), axis=1)
    residual_component = 1.0 / (
        1.0 + np.exp(-(max_residual - residual_center) / residual_scale)
    )
    return 0.62 * if_component + 0.38 * residual_component


def fit_sequence_model(normal: list[Any], seed: int) -> SequenceModel:
    fit_rows, calibration_rows = _training_windows(normal)
    matrix = _matrix(fit_rows)
    median = np.median(matrix, axis=0)
    iqr = np.quantile(matrix, 0.75, axis=0) - np.quantile(matrix, 0.25, axis=0)
    iqr[iqr < 1e-6] = 1.0
    scaled = (matrix - median) / iqr
    model = IsolationForest(
        n_estimators=180,
        contamination=0.01,
        max_samples=min(512, len(fit_rows)),
        random_state=seed + 7000,
        n_jobs=-1,
    ).fit(scaled)
    fit_residuals = np.max(np.abs(scaled), axis=1)
    residual_center = float(np.median(fit_residuals))
    residual_scale = max(
        0.25,
        float(np.quantile(fit_residuals, 0.75) - np.quantile(fit_residuals, 0.25)),
    )
    calibration_scores = _base_scores(
        model, median, iqr, residual_center, residual_scale, calibration_rows
    )
    spread = max(
        0.005,
        float(np.quantile(calibration_scores, 0.75) - np.quantile(calibration_scores, 0.25)),
    )
    # Thresholds are derived from normal-only calibration.  A small robust
    # margin prevents a single tiny calibration cell from setting an unstable
    # boundary equal to its maximum observation.
    warn = min(0.995, float(np.quantile(calibration_scores, 0.99)) + 0.10 * spread)
    challenge = min(0.999, float(np.quantile(calibration_scores, 0.997)) + 0.35 * spread)
    challenge = max(challenge, warn + 0.01)
    return SequenceModel(
        model=model,
        median=median,
        iqr=iqr,
        residual_center=residual_center,
        residual_scale=residual_scale,
        warn_threshold=warn,
        challenge_threshold=challenge,
        fit_count=len(fit_rows),
        calibration_count=len(calibration_rows),
    )


def score_sequence(model: SequenceModel, events: list[Any]) -> float:
    row = sequence_features(events)
    return float(
        _base_scores(
            model.model,
            model.median,
            model.iqr,
            model.residual_center,
            model.residual_scale,
            [row],
        )[0]
    )


def _apply_sequence_decision(v3_decision: str, risk: float, model: SequenceModel) -> str:
    level = V3.V2.ACTION_LEVEL[v3_decision]
    if risk > model.challenge_threshold:
        level = max(level, 2)
    elif risk > model.warn_threshold:
        level = max(level, 1)
    return ("allow", "warn", "challenge", "block")[level]


def _base_record(
    row: dict[str, Any], raw: float, train_count: int, phase: Any | None = None
) -> dict[str, Any]:
    score, decision = V3._v3_decision(row, raw, train_count)
    event = row["event"]
    return {
        "profile_id": event.profile_id,
        "sequence_id": phase.sequence_id if phase else None,
        "attack_type": phase.attack_type if phase else None,
        "phase_index": phase.phase_index if phase else 0,
        "objective_phase": phase.objective_phase if phase else False,
        "label": int(phase is not None),
        "event_score": score,
        "decision": decision,
        "anomaly_score": score,
    }


def _metrics(normal: list[dict[str, Any]], attacks: list[dict[str, Any]]) -> dict[str, float]:
    detected = lambda row: V3.V2.ACTION_LEVEL[row["decision"]] >= 2
    tp = sum(detected(row) for row in attacks)
    fp = sum(detected(row) for row in normal)
    fn = len(attacks) - tp
    tn = len(normal) - fp
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    labels = np.asarray([0] * len(normal) + [1] * len(attacks), dtype=int)
    scores = np.asarray([row["anomaly_score"] for row in normal + attacks], dtype=float)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in attacks:
        grouped[row["sequence_id"]].append(row)
    sequence_hits = pre_hits = objective_hits = 0
    times: list[int] = []
    for rows in grouped.values():
        ordered = sorted(rows, key=lambda value: value["phase_index"])
        hits = [row["phase_index"] for row in ordered if detected(row)]
        sequence_hits += bool(hits)
        pre_hits += any(detected(row) and not row["objective_phase"] for row in ordered)
        objective_hits += any(detected(row) and row["objective_phase"] for row in ordered)
        times.append(min(hits) if hits else V4.PHASES_PER_SEQUENCE + 1)
    poison = [row for row in attacks if row["attack_type"] == "profile_poisoning_chain" and V3.V2.ACTION_LEVEL[row["decision"]] >= 1]
    rejected = sum(not V3.is_trusted_decision("would_" + row["decision"]) for row in poison)
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": precision,
        "event_challenge_recall": recall,
        "f1": 2 * precision * recall / max(1e-12, precision + recall),
        "roc_auc": float(roc_auc_score(labels, scores)) if len(set(labels)) > 1 else 0.0,
        "pr_auc": float(average_precision_score(labels, scores)) if len(set(labels)) > 1 else 0.0,
        "challenge_fpr": fp / max(1, len(normal)),
        "warn_fpr": sum(V3.V2.ACTION_LEVEL[row["decision"]] >= 1 for row in normal) / max(1, len(normal)),
        "block_fpr": sum(V3.V2.ACTION_LEVEL[row["decision"]] >= 3 for row in normal) / max(1, len(normal)),
        "sequence_detection_rate": sequence_hits / max(1, len(grouped)),
        "preobjective_detection_rate": pre_hits / max(1, len(grouped)),
        "objective_detection_rate": objective_hits / max(1, len(grouped)),
        "median_time_to_detect_phase": float(np.median(times)) if times else 0.0,
        "flagged_poison_rejection_rate": rejected / max(1, len(poison)),
        "normal_count": len(normal),
        "attack_phase_count": len(attacks),
        "attack_sequence_count": len(grouped),
    }


def score_run(
    users: list[dict[str, Any]], size: int, seed: int, scenario: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    normal = V3.generate_normal(users, size, seed, scenario)
    phases = V4.generate_attack_sequences(users, normal, seed + 50_000, scenario)
    phase_map = {id(phase.event): phase for phase in phases}
    normal_rows, attack_rows = V3.build_features(normal, [phase.event for phase in phases])
    train_rows = [row for row in normal_rows if row["event"].split == "train"]
    normal_eval_rows = [row for row in normal_rows if row["event"].split == "normal_test"]
    evaluation_rows = normal_eval_rows + attack_rows
    event_model, event_median, event_iqr = V3.V2._fit_iforest(train_rows, seed, V3.ML_FEATURES)
    event_raw = V3.V2._raw_ml(event_model, event_median, event_iqr, evaluation_rows, V3.ML_FEATURES)
    raw_map = {id(row["event"]): float(event_raw[index]) for index, row in enumerate(evaluation_rows)}
    row_map = {id(row["event"]): row for row in evaluation_rows}
    train_counts = Counter(row["event"].profile_id for row in train_rows)
    sequence_model = fit_sequence_model(normal, seed)

    v3_normal: list[dict[str, Any]] = []
    v5_normal: list[dict[str, Any]] = []
    normal_pending: list[tuple[dict[str, Any], dict[str, float]]] = []
    normal_by_profile = _profile_events(normal)
    for profile_id, events in normal_by_profile.items():
        history = [event for event in events if event.split == "train"]
        tests = [event for event in events if event.split == "normal_test"]
        for event in tests:
            row = row_map[id(event)]
            base = _base_record(row, raw_map[id(event)], train_counts[profile_id])
            v3_normal.append(base)
            history.append(event)
            normal_pending.append((base, sequence_features(history)))
    normal_risks = _base_scores(
        sequence_model.model,
        sequence_model.median,
        sequence_model.iqr,
        sequence_model.residual_center,
        sequence_model.residual_scale,
        [features for _, features in normal_pending],
    )
    for (base, _), risk_value in zip(normal_pending, normal_risks):
        risk = float(risk_value)
        v5_normal.append(
            {
                **base,
                "decision": _apply_sequence_decision(base["decision"], risk, sequence_model),
                "anomaly_score": max(base["anomaly_score"], risk),
                "sequence_score": risk,
            }
        )

    v3_attacks: list[dict[str, Any]] = []
    v5_attacks: list[dict[str, Any]] = []
    attack_pending: list[tuple[dict[str, Any], dict[str, float]]] = []
    phases_by_sequence: dict[str, list[Any]] = defaultdict(list)
    for phase in phases:
        phases_by_sequence[phase.sequence_id].append(phase)
    trusted_by_profile = _profile_events(normal)
    for sequence_phases in phases_by_sequence.values():
        sequence_phases.sort(key=lambda phase: phase.phase_index)
        profile_id = sequence_phases[0].event.profile_id
        observation_history = list(trusted_by_profile[profile_id])
        for phase in sequence_phases:
            row = row_map[id(phase.event)]
            base = _base_record(row, raw_map[id(phase.event)], train_counts[profile_id], phase)
            v3_attacks.append(base)
            observation_history.append(phase.event)
            attack_pending.append((base, sequence_features(observation_history)))
    attack_risks = _base_scores(
        sequence_model.model,
        sequence_model.median,
        sequence_model.iqr,
        sequence_model.residual_center,
        sequence_model.residual_scale,
        [features for _, features in attack_pending],
    )
    for (base, _), risk_value in zip(attack_pending, attack_risks):
        risk = float(risk_value)
        v5_attacks.append(
            {
                **base,
                "decision": _apply_sequence_decision(base["decision"], risk, sequence_model),
                "anomaly_score": max(base["anomaly_score"], risk),
                "sequence_score": risk,
            }
        )

    stage_rows: list[dict[str, Any]] = []
    attack_rows_out: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    for stage, normal_records, attack_records in (
        ("hardened_v3_event", v3_normal, v3_attacks),
        ("sequence_model_v5", v5_normal, v5_attacks),
    ):
        stage_rows.append(
            {
                "stage": stage,
                "dataset_size": size,
                "seed": seed,
                "normal_scenario": scenario,
                "sequence_fit_count": sequence_model.fit_count,
                "sequence_calibration_count": sequence_model.calibration_count,
                "warn_threshold": sequence_model.warn_threshold,
                "challenge_threshold": sequence_model.challenge_threshold,
                **_metrics(normal_records, attack_records),
            }
        )
        for attack_type in V4.ATTACKS:
            subset = [row for row in attack_records if row["attack_type"] == attack_type]
            if subset:
                attack_rows_out.append(
                    {
                        "stage": stage,
                        "dataset_size": size,
                        "seed": seed,
                        "normal_scenario": scenario,
                        "attack_type": attack_type,
                        **{key: value for key, value in _metrics([], subset).items() if key not in {"challenge_fpr", "warn_fpr", "block_fpr", "normal_count"}},
                    }
                )
        for row in normal_records + attack_records:
            prediction_rows.append(
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
    return stage_rows, attack_rows_out, prediction_rows


def _release_gates(stages: pd.DataFrame, attacks: pd.DataFrame) -> dict[str, Any]:
    v5 = stages[stages.stage.eq("sequence_model_v5")]
    cold = v5[v5.dataset_size.eq(10)]
    family = attacks[attacks.stage.eq("sequence_model_v5")].groupby("attack_type").sequence_detection_rate.mean()
    scenario = v5.groupby("normal_scenario").sequence_detection_rate.mean()
    checks = {
        "challenge_fpr_le_0_003": float(v5.challenge_fpr.mean()) <= 0.003,
        "warn_fpr_le_0_01": float(v5.warn_fpr.mean()) <= 0.01,
        "sequence_detection_ge_0_90": float(v5.sequence_detection_rate.mean()) >= 0.90,
        "minimum_attack_family_detection_ge_0_80": float(family.min()) >= 0.80,
        "preobjective_detection_ge_0_70": float(v5.preobjective_detection_rate.mean()) >= 0.70,
        "median_time_to_detect_le_2": float(v5.median_time_to_detect_phase.median()) <= 2.0,
        "cold_sequence_detection_ge_0_85": float(cold.sequence_detection_rate.mean()) >= 0.85,
        "nat_detection_gap_le_0_02": float(scenario.max() - scenario.min()) <= 0.02,
        "flagged_poison_rejection_eq_1": float(v5.flagged_poison_rejection_rate.mean()) == 1.0,
        "ready_for_enforcement_is_false": True,
    }
    return {
        "ready_for_system_integration_shadow": all(checks.values()),
        "ready_for_enforcement": False,
        "checks": checks,
        "observed": {
            "precision": float(v5.precision.mean()),
            "event_challenge_recall": float(v5.event_challenge_recall.mean()),
            "f1": float(v5.f1.mean()),
            "roc_auc": float(v5.roc_auc.mean()),
            "pr_auc": float(v5.pr_auc.mean()),
            "challenge_fpr": float(v5.challenge_fpr.mean()),
            "warn_fpr": float(v5.warn_fpr.mean()),
            "sequence_detection_rate": float(v5.sequence_detection_rate.mean()),
            "minimum_attack_family_detection": float(family.min()),
            "preobjective_detection_rate": float(v5.preobjective_detection_rate.mean()),
            "objective_detection_rate": float(v5.objective_detection_rate.mean()),
            "median_time_to_detect_phase": float(v5.median_time_to_detect_phase.median()),
            "cold_sequence_detection_rate": float(cold.sequence_detection_rate.mean()),
            "nat_detection_gap": float(scenario.max() - scenario.min()),
            "flagged_poison_rejection_rate": float(v5.flagged_poison_rejection_rate.mean()),
        },
        "note": "Passing permits isolated shadow integration only. Production replay, latency tests, model serialization validation, monitoring, and canary are still required.",
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
        "version": 5,
        "mode": "isolated_sequence_model_shadow",
        "fixed_ip": "192.168.10.1",
        "geo": None,
        "normal_train_fraction": 0.8,
        "normal_fit_fraction_within_train": 0.75,
        "window_size": WINDOW,
        "training_labels": "trusted normal only",
        "attack_threshold_tuning": False,
        "attack_seed_offset": 50_000,
        "sequence_features": SEQUENCE_FEATURES,
        "trusted_decisions": sorted(V3.TRUSTED_DECISIONS),
        "ready_for_enforcement": False,
    }
    (output / "sequence_contract_v5.json").write_text(
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
