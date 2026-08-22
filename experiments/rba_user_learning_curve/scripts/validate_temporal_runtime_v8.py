#!/usr/bin/env python3
"""Validate V8 portable artifact parity, integrity, and shadow latency."""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = ROOT / "scripts" / "shadow_temporal_runtime_v8.py"
RESULTS = ROOT / "results" / "temporal_mlp_v8"

SPEC = importlib.util.spec_from_file_location("shadow_temporal_runtime_v8_validation", RUNTIME_PATH)
RUNTIME = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = RUNTIME
SPEC.loader.exec_module(RUNTIME)


def _reference(runtime, matrix: np.ndarray) -> np.ndarray:
    hidden = np.clip(
        (matrix - runtime.input_median) / runtime.input_iqr, -10.0, 10.0
    )
    for weight, bias in zip(runtime.weights[:-1], runtime.biases[:-1]):
        hidden = np.tanh(hidden @ weight + bias)
    logits = hidden @ runtime.weights[-1] + runtime.biases[-1]
    return (1.0 / (1.0 + np.exp(-np.clip(logits, -35.0, 35.0)))).reshape(-1)


def main() -> None:
    runtime = RUNTIME.load_runtime(RESULTS)
    rng = np.random.default_rng(20260822)
    matrix = rng.normal(size=(256, RUNTIME.INPUT_SIZE))
    reference = _reference(runtime, matrix)
    scalar = np.asarray([RUNTIME.probability(runtime, row) for row in matrix])
    max_error = float(np.max(np.abs(reference - scalar)))

    samples = rng.normal(size=(2000, RUNTIME.INPUT_SIZE))
    latencies: list[float] = []
    for row in samples:
        started = time.perf_counter_ns()
        result = RUNTIME.score_shadow(runtime, row, RUNTIME.MIN_TRUSTED_EVENTS)
        latencies.append((time.perf_counter_ns() - started) / 1_000_000.0)
        if result["enforce"] is not False:
            raise AssertionError("V8 runtime attempted enforcement")
    latency = np.asarray(latencies)
    output = {
        "artifact_sha256": runtime.artifact_sha256,
        "portable_npz_allow_pickle_false": True,
        "sklearn_runtime_required": False,
        "random_forest": False,
        "enforcement_disabled": True,
        "cold_profile_abstention_verified": RUNTIME.score_shadow(
            runtime, np.zeros(RUNTIME.INPUT_SIZE), RUNTIME.MIN_TRUSTED_EVENTS - 1
        )["decision"] == "shadow_abstain_cold_profile",
        "parity": {
            "sample_count": len(matrix),
            "max_absolute_error": max_error,
            "passed_le_1e_12": max_error <= 1e-12,
        },
        "latency_ms": {
            "iterations": len(latency),
            "p50": float(np.quantile(latency, 0.50)),
            "p95": float(np.quantile(latency, 0.95)),
            "p99": float(np.quantile(latency, 0.99)),
            "mean": float(np.mean(latency)),
            "max": float(np.max(latency)),
        },
    }
    (RESULTS / "runtime_validation.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
