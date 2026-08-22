#!/usr/bin/env python3
"""Portable NumPy-only shadow runtime for the standalone V8 temporal MLP."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE_DIR = ROOT / "results" / "temporal_mlp_v8"
INPUT_SIZE = 64
MIN_TRUSTED_EVENTS = 1000


@dataclass(frozen=True)
class ShadowRuntime:
    weights: tuple[np.ndarray, ...]
    biases: tuple[np.ndarray, ...]
    input_median: np.ndarray
    input_iqr: np.ndarray
    challenge_threshold: float
    warn_threshold: float
    behavior_warn_threshold: float
    artifact_sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_runtime(bundle_dir: Path = DEFAULT_BUNDLE_DIR) -> ShadowRuntime:
    contract = json.loads((bundle_dir / "model_contract_v8.json").read_text(encoding="utf-8"))
    artifact_metadata = contract["artifact"]
    artifact = bundle_dir / artifact_metadata["path"]
    actual_sha = _sha256(artifact)
    if actual_sha != artifact_metadata["sha256"]:
        raise ValueError(
            f"V8 artifact checksum mismatch: expected {artifact_metadata['sha256']}, got {actual_sha}"
        )
    with np.load(artifact, allow_pickle=False) as payload:
        weights = tuple(payload[f"weight_{index}"].copy() for index in range(3))
        biases = tuple(payload[f"bias_{index}"].copy() for index in range(3))
        median = payload["input_median"].copy()
        iqr = payload["input_iqr"].copy()
        challenge = float(payload["challenge_threshold"][0])
        warn = float(payload["warn_threshold"][0])
        behavior = float(payload["behavior_warn_threshold"][0])
    expected_shapes = ((INPUT_SIZE, 32), (32, 12), (12, 1))
    if tuple(weight.shape for weight in weights) != expected_shapes:
        raise ValueError(f"invalid V8 weight shapes: {[weight.shape for weight in weights]}")
    if median.shape != (INPUT_SIZE,) or iqr.shape != (INPUT_SIZE,):
        raise ValueError("invalid V8 input scaler shape")
    if not np.all(np.isfinite(median)) or not np.all(np.isfinite(iqr)):
        raise ValueError("non-finite V8 scaler")
    if np.any(iqr <= 0.0):
        raise ValueError("non-positive V8 input scale")
    return ShadowRuntime(
        weights=weights,
        biases=biases,
        input_median=median,
        input_iqr=iqr,
        challenge_threshold=challenge,
        warn_threshold=warn,
        behavior_warn_threshold=behavior,
        artifact_sha256=actual_sha,
    )


def _sigmoid(value: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(value, -35.0, 35.0)))


def probability(runtime: ShadowRuntime, feature_vector: np.ndarray) -> float:
    vector = np.asarray(feature_vector, dtype=float)
    if vector.shape != (INPUT_SIZE,):
        raise ValueError(f"V8 feature vector must have shape ({INPUT_SIZE},)")
    if not np.all(np.isfinite(vector)):
        raise ValueError("V8 feature vector contains non-finite values")
    hidden = np.clip((vector - runtime.input_median) / runtime.input_iqr, -10.0, 10.0)
    for weight, bias in zip(runtime.weights[:-1], runtime.biases[:-1]):
        hidden = np.tanh(hidden @ weight + bias)
    return float(_sigmoid(hidden @ runtime.weights[-1] + runtime.biases[-1]).reshape(-1)[0])


def score_shadow(
    runtime: ShadowRuntime, feature_vector: np.ndarray, trusted_event_count: int
) -> dict[str, Any]:
    """Return a shadow label only; this function cannot enforce an action."""
    if trusted_event_count < MIN_TRUSTED_EVENTS:
        return {
            "eligible": False,
            "probability": None,
            "decision": "shadow_abstain_cold_profile",
            "enforce": False,
            "minimum_trusted_events": MIN_TRUSTED_EVENTS,
        }
    risk = probability(runtime, feature_vector)
    if risk >= runtime.challenge_threshold:
        decision = "would_challenge"
    elif risk >= runtime.warn_threshold:
        decision = "would_warn"
    else:
        decision = "would_allow"
    return {
        "eligible": True,
        "probability": risk,
        "decision": decision,
        "enforce": False,
        "minimum_trusted_events": MIN_TRUSTED_EVENTS,
    }
