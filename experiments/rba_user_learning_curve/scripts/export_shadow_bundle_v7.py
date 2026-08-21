#!/usr/bin/env python3
"""Export and validate the V7 deployment candidate for shadow-only loading."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn

ROOT = Path(__file__).resolve().parents[1]
V6_PATH = ROOT / "scripts" / "run_supervised_sequence_v6.py"
RUNTIME_PATH = ROOT / "scripts" / "shadow_sequence_runtime_v7.py"
V6_RESULTS = ROOT / "results" / "supervised_sequence_v6"
RESULTS_DIR = ROOT / "results" / "deployable_bundle_v7"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V6 = _load("supervised_sequence_v6", V6_PATH)
RUNTIME = _load("shadow_sequence_runtime_v7", RUNTIME_PATH)


def _payload(event: Any) -> dict[str, Any]:
    return {
        "timestamp": event.timestamp.isoformat(),
        "failed_1h": event.failed_1h,
        "success_10m": event.success_10m,
        "concurrent_sessions": event.concurrent_sessions,
        "session_duration": event.session_duration,
        "scope_sensitivity": event.scope_sensitivity,
        "browser_version": event.browser_version,
        "subsystem": event.subsystem,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable_forest(model: Any) -> dict[str, Any]:
    """Export sklearn's fitted forest without persisting sklearn objects."""
    classes = [int(value) for value in model.classes_]
    if classes != [0, 1]:
        raise ValueError(f"expected binary classes [0, 1], got {classes}")
    trees: list[dict[str, Any]] = []
    for estimator in model.estimators_:
        tree = estimator.tree_
        values = tree.value[:, 0, :]
        denominators = values.sum(axis=1)
        class_one = np.divide(
            values[:, 1],
            denominators,
            out=np.zeros_like(denominators, dtype=float),
            where=denominators != 0,
        )
        trees.append(
            {
                "children_left": tree.children_left.astype(int).tolist(),
                "children_right": tree.children_right.astype(int).tolist(),
                "feature": tree.feature.astype(int).tolist(),
                "threshold": tree.threshold.astype(float).tolist(),
                "probability_class_1": class_one.astype(float).tolist(),
            }
        )
    return {
        "n_features": int(model.n_features_in_),
        "n_classes": 2,
        "trees": trees,
    }


def export(output: Path, dataset_size: int, seed: int, scenario: str, latency_iterations: int) -> None:
    users = V6.V3.V2._load_users()
    normal = V6.V3.generate_normal(users, dataset_size, seed, scenario)
    fitted = V6.fit_supervised_model(users, normal, seed, scenario)
    output.mkdir(parents=True, exist_ok=True)
    bundle_path = output / "sequence_model_v7.joblib"
    bundle = {
        "version": "7.1.0-shadow-portable",
        "model_format": RUNTIME.PORTABLE_MODEL_FORMAT,
        "portable_model": _portable_forest(fitted.model),
        "median": fitted.median.tolist(),
        "iqr": fitted.iqr.tolist(),
        "challenge_threshold": fitted.challenge_threshold,
        "feature_names": V6.V5.SEQUENCE_FEATURES,
        "window_size": V6.V5.WINDOW,
        "enforcement_enabled": False,
        "training_mode": "synthetic_candidate",
        "training_sklearn_version": sklearn.__version__,
        "runtime_sklearn_required": False,
    }
    joblib.dump(bundle, bundle_path, compress=3)
    runtime = RUNTIME.ShadowSequenceRuntime(bundle_path)

    by_profile = V6.V5._profile_events(normal)
    normal_windows = [list(events[-4:]) for events in by_profile.values()]
    phases = V6.V4.generate_attack_sequences(
        users, normal, seed + V6.TEST_ATTACK_OFFSET, scenario
    )
    phase_groups: dict[str, list[Any]] = {}
    for phase in phases:
        phase_groups.setdefault(phase.sequence_id, []).append(phase)
    attack_windows: list[list[Any]] = []
    for group in phase_groups.values():
        ordered = sorted(group, key=lambda phase: phase.phase_index)
        history = list(by_profile[ordered[0].event.profile_id])
        for phase in ordered:
            history.append(phase.event)
            attack_windows.append(list(history[-4:]))
    windows = normal_windows + attack_windows[: max(12, len(normal_windows))]
    feature_rows = [V6.V5.sequence_features(events) for events in windows]
    expected = V6._probabilities(
        fitted.model, fitted.median, fitted.iqr, feature_rows
    )
    actual = np.asarray(
        [runtime.score([_payload(event) for event in events]) for events in windows],
        dtype=float,
    )
    errors = np.abs(expected - actual)
    parity = {
        "sample_count": len(windows),
        "max_absolute_error": float(errors.max()),
        "mean_absolute_error": float(errors.mean()),
        "passed": float(errors.max()) <= 1e-12,
    }
    (output / "serialization_parity.json").write_text(
        json.dumps(parity, indent=2) + "\n", encoding="utf-8"
    )

    benchmark_payload = [_payload(event) for event in attack_windows[-1]]
    for _ in range(30):
        runtime.evaluate(benchmark_payload)
    latency_ms: list[float] = []
    for _ in range(latency_iterations):
        started = time.perf_counter_ns()
        runtime.evaluate(benchmark_payload)
        latency_ms.append((time.perf_counter_ns() - started) / 1_000_000.0)
    latency = {
        "iterations": latency_iterations,
        "p50_ms": float(np.quantile(latency_ms, 0.50)),
        "p95_ms": float(np.quantile(latency_ms, 0.95)),
        "p99_ms": float(np.quantile(latency_ms, 0.99)),
        "mean_ms": float(statistics.mean(latency_ms)),
        "max_ms": float(max(latency_ms)),
    }
    pd.DataFrame([latency]).to_csv(output / "latency_results.csv", index=False)

    for filename in (
        "stage_run_results.csv",
        "stage_aggregate_results.csv",
        "attack_sequence_run_results.csv",
        "attack_sequence_aggregate_results.csv",
        "predictions.csv",
    ):
        shutil.copy2(V6_RESULTS / filename, output / filename)
    v6_gate = json.loads((V6_RESULTS / "release_gate.json").read_text(encoding="utf-8"))
    checks = {
        "v6_synthetic_shadow_gate": bool(v6_gate["ready_for_system_integration_shadow"]),
        "serialization_parity_max_error_le_1e_12": parity["passed"],
        "single_score_p95_le_20ms": latency["p95_ms"] <= 20.0,
        "single_score_p99_le_35ms": latency["p99_ms"] <= 35.0,
        "runtime_enforcement_disabled": runtime.evaluate(benchmark_payload)["enforcement_applied"] is False,
        "feature_contract_exact": tuple(bundle["feature_names"]) == RUNTIME.SEQUENCE_FEATURES,
        "bundle_sha256_present": len(_sha256(bundle_path)) == 64,
        "portable_model_format": bundle["model_format"] == RUNTIME.PORTABLE_MODEL_FORMAT,
        "runtime_sklearn_not_required": bundle["runtime_sklearn_required"] is False,
    }
    gate = {
        "ready_for_system_shadow_load": all(checks.values()),
        "ready_for_enforcement": False,
        "checks": checks,
        "observed": {
            **v6_gate["observed"],
            **latency,
            "serialization_max_absolute_error": parity["max_absolute_error"],
            "bundle_size_bytes": bundle_path.stat().st_size,
        },
        "note": "This bundle can be loaded only in shadow mode. It is trained on synthetic data; anonymized production replay and canary approval are mandatory before any enforcement.",
    }
    (output / "release_gate.json").write_text(
        json.dumps(gate, indent=2) + "\n", encoding="utf-8"
    )
    contract = {
        "version": 7,
        "runtime_version": bundle["version"],
        "mode": "shadow_only",
        "window_size": V6.V5.WINDOW,
        "required_event_fields": sorted(RUNTIME.REQUIRED_EVENT_FIELDS),
        "sequence_features": V6.V5.SEQUENCE_FEATURES,
        "challenge_threshold": fitted.challenge_threshold,
        "bundle_sha256": _sha256(bundle_path),
        "enforcement_enabled": False,
        "model_format": bundle["model_format"],
        "training_sklearn_version": bundle["training_sklearn_version"],
        "runtime_sklearn_required": False,
        "training_dataset_size": dataset_size,
        "training_seed": seed,
        "training_scenario": scenario,
    }
    (output / "runtime_contract_v7.json").write_text(
        json.dumps(contract, indent=2) + "\n", encoding="utf-8"
    )
    manifest_files = {
        "sequence_model_v7.joblib": _sha256(bundle_path),
        "runtime_contract_v7.json": _sha256(output / "runtime_contract_v7.json"),
        "serialization_parity.json": _sha256(output / "serialization_parity.json"),
        "latency_results.csv": _sha256(output / "latency_results.csv"),
    }
    manifest = {
        "artifact_format": bundle["model_format"],
        "training_sklearn_version": bundle["training_sklearn_version"],
        "runtime_sklearn_required": False,
        "files": manifest_files,
        "file_sizes": {
            filename: (output / filename).stat().st_size for filename in manifest_files
        },
    }
    (output / "model_manifest_v7.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=RESULTS_DIR)
    parser.add_argument("--dataset-size", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--scenario", default="normal_staggered")
    parser.add_argument("--latency-iterations", type=int, default=1000)
    args = parser.parse_args()
    export(args.output, args.dataset_size, args.seed, args.scenario, args.latency_iterations)


if __name__ == "__main__":
    main()
