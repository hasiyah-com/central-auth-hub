#!/usr/bin/env python3
"""Self-contained runtime for the portable V7 RBA shadow bundle.

The shipped artifact deliberately contains no scikit-learn estimator.  This
keeps request-path inference independent from the scikit-learn version used to
train the forest.
"""

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
PORTABLE_MODEL_FORMAT = "portable-random-forest-v1"


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


def _validate_portable_forest(forest: Any) -> None:
    if not isinstance(forest, dict) or not isinstance(forest.get("trees"), list):
        raise ValueError("bundle does not contain a portable random forest")
    if not forest["trees"]:
        raise ValueError("portable random forest contains no trees")
    required = {
        "children_left",
        "children_right",
        "feature",
        "threshold",
        "probability_class_1",
    }
    for index, tree in enumerate(forest["trees"]):
        if not isinstance(tree, dict) or required - set(tree):
            raise ValueError(f"portable tree {index} is incomplete")
        lengths = {len(tree[name]) for name in required}
        if len(lengths) != 1 or next(iter(lengths)) == 0:
            raise ValueError(f"portable tree {index} has inconsistent arrays")


def _portable_probability(forest: dict[str, Any], row: list[float]) -> float:
    # sklearn's tree traversal casts inputs to float32 before comparing them to
    # the stored float64 thresholds.  Matching that cast is required for exact
    # leaf parity when a normalized feature lies extremely close to a split.
    row = np.asarray(row, dtype=np.float32).astype(float).tolist()
    total = 0.0
    for tree in forest["trees"]:
        node = 0
        while tree["children_left"][node] != -1:
            feature = tree["feature"][node]
            node = (
                tree["children_left"][node]
                if row[feature] <= tree["threshold"][node]
                else tree["children_right"][node]
            )
        total += tree["probability_class_1"][node]
    return total / len(forest["trees"])


class ShadowSequenceRuntime:
    """Load a signed-off experiment bundle and emit shadow labels only."""

    def __init__(self, bundle_path: Path | str):
        bundle = joblib.load(bundle_path)
        if tuple(bundle.get("feature_names", ())) != SEQUENCE_FEATURES:
            raise ValueError("bundle feature contract does not match V7 runtime")
        if bundle.get("enforcement_enabled") is not False:
            raise ValueError("V7 runtime refuses enforcement-enabled bundles")
        if bundle.get("model_format") != PORTABLE_MODEL_FORMAT:
            raise ValueError("V7 runtime refuses non-portable sklearn bundles")
        if bundle.get("runtime_sklearn_required") is not False:
            raise ValueError("portable V7 bundle must not require sklearn at runtime")
        self.forest = bundle["portable_model"]
        _validate_portable_forest(self.forest)
        self.median = np.asarray(bundle["median"], dtype=float)
        self.iqr = np.asarray(bundle["iqr"], dtype=float)
        self.threshold = float(bundle["challenge_threshold"])
        self.version = str(bundle["version"])

    def score(self, events: list[dict[str, Any]]) -> float:
        features = sequence_features(events)
        matrix = np.asarray([[features[name] for name in SEQUENCE_FEATURES]], dtype=float)
        scaled = (matrix - self.median) / self.iqr
        return float(_portable_probability(self.forest, scaled[0].tolist()))

    def evaluate(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        probability = self.score(events)
        return {
            "model_version": self.version,
            "sequence_probability": probability,
            "shadow_decision": "would_challenge" if probability >= self.threshold else "observe",
            "enforcement_applied": False,
        }
