#!/usr/bin/env python3
"""Self-contained runtime for the V7 RBA sequence shadow bundle."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np

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
REQUIRED_EVENT_FIELDS = frozenset(
    {
        "timestamp",
        "failed_1h",
        "success_10m",
        "concurrent_sessions",
        "session_duration",
        "scope_sensitivity",
        "browser_version",
        "subsystem",
    }
)


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise TypeError("timestamp must be datetime or ISO-8601 string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _validate(events: list[dict[str, Any]]) -> None:
    if len(events) < WINDOW:
        raise ValueError(f"at least {WINDOW} chronological events are required")
    for index, event in enumerate(events[-WINDOW:]):
        missing = REQUIRED_EVENT_FIELDS - set(event)
        if missing:
            raise ValueError(f"event {index} missing fields: {sorted(missing)}")


def _slope(values: list[float]) -> float:
    x = np.arange(len(values), dtype=float)
    return float(np.polyfit(x, np.asarray(values, dtype=float), 1)[0])


def sequence_features(events: list[dict[str, Any]]) -> dict[str, float]:
    _validate(events)
    items = sorted(events[-WINDOW:], key=lambda event: _timestamp(event["timestamp"]))
    timestamps = [_timestamp(event["timestamp"]) for event in items]
    gaps = [
        max(0.5, (right - left).total_seconds() / 60.0)
        for left, right in zip(timestamps, timestamps[1:])
    ]
    gap_logs = [math.log1p(value) for value in gaps]
    durations = [math.log1p(max(0.0, float(event["session_duration"]))) for event in items]
    scopes = [float(event["scope_sensitivity"]) for event in items]
    versions = [float(event["browser_version"]) for event in items]
    angles = np.asarray([2.0 * math.pi * value.hour / 24.0 for value in timestamps])
    switches = sum(
        left["subsystem"] != right["subsystem"] for left, right in zip(items, items[1:])
    )
    return {
        "gap_log_mean": float(np.mean(gap_logs)),
        "gap_log_range": float(max(gap_logs) - min(gap_logs)),
        "rapid_gap_count": float(sum(value <= 35.0 for value in gaps)),
        "failed_sum": float(sum(int(event["failed_1h"]) for event in items)),
        "success_sum": float(sum(int(event["success_10m"]) for event in items)),
        "concurrent_sum": float(sum(int(event["concurrent_sessions"]) for event in items)),
        "duration_log_slope": _slope(durations),
        "duration_log_range": float(max(durations) - min(durations)),
        "scope_slope": _slope(scopes),
        "scope_duration_growth": float(
            max(0.0, durations[-1] - durations[0])
            * max(scopes[-1], float(np.mean(scopes)))
        ),
        "browser_version_slope": _slope(versions),
        "subsystem_switch_rate": switches / 3.0,
        "hour_circular_spread": 1.0 - float(abs(np.mean(np.exp(1j * angles)))),
    }


class ShadowSequenceRuntime:
    """Load a signed-off experiment bundle and emit shadow labels only."""

    def __init__(self, bundle_path: Path | str):
        bundle = joblib.load(bundle_path)
        if tuple(bundle.get("feature_names", ())) != SEQUENCE_FEATURES:
            raise ValueError("bundle feature contract does not match V7 runtime")
        if bundle.get("enforcement_enabled") is not False:
            raise ValueError("V7 runtime refuses enforcement-enabled bundles")
        self.model = bundle["model"]
        # Parallel tree traversal is useful for large offline batches but adds
        # substantial thread-launch overhead for one login at a time.
        if hasattr(self.model, "n_jobs"):
            self.model.n_jobs = 1
        self.median = np.asarray(bundle["median"], dtype=float)
        self.iqr = np.asarray(bundle["iqr"], dtype=float)
        self.threshold = float(bundle["challenge_threshold"])
        self.version = str(bundle["version"])

    def score(self, events: list[dict[str, Any]]) -> float:
        features = sequence_features(events)
        matrix = np.asarray([[features[name] for name in SEQUENCE_FEATURES]], dtype=float)
        scaled = (matrix - self.median) / self.iqr
        return float(self.model.predict_proba(scaled)[0, 1])

    def evaluate(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        probability = self.score(events)
        return {
            "model_version": self.version,
            "sequence_probability": probability,
            "shadow_decision": "would_challenge" if probability >= self.threshold else "observe",
            "enforcement_applied": False,
        }
