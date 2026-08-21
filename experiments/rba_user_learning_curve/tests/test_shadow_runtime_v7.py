from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "shadow_sequence_runtime_v7.py"
SPEC = importlib.util.spec_from_file_location("shadow_sequence_runtime_v7_test", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _events():
    return [
        {
            "timestamp": f"2024-01-0{index + 1}T09:00:00",
            "failed_1h": 0,
            "success_10m": 0,
            "concurrent_sessions": 0,
            "session_duration": 15.0 + index,
            "scope_sensitivity": 0.6,
            "browser_version": 150,
            "subsystem": "library",
        }
        for index in range(4)
    ]


def _bundle(path: Path, enforcement=False):
    matrix = np.asarray([[0.0] * len(MODULE.SEQUENCE_FEATURES), [1.0] * len(MODULE.SEQUENCE_FEATURES)])
    model = RandomForestClassifier(n_estimators=4, random_state=42).fit(matrix, [0, 1])
    joblib.dump(
        {
            "version": "7-test",
            "model": model,
            "median": np.zeros(len(MODULE.SEQUENCE_FEATURES)),
            "iqr": np.ones(len(MODULE.SEQUENCE_FEATURES)),
            "challenge_threshold": 0.5,
            "feature_names": MODULE.SEQUENCE_FEATURES,
            "enforcement_enabled": enforcement,
        },
        path,
    )


def test_runtime_requires_four_events():
    try:
        MODULE.sequence_features(_events()[:3])
    except ValueError:
        return
    raise AssertionError("runtime accepted fewer than four events")


def test_runtime_rejects_missing_fields():
    events = _events()
    del events[-1]["session_duration"]
    try:
        MODULE.sequence_features(events)
    except ValueError:
        return
    raise AssertionError("runtime accepted an incomplete event")


def test_runtime_refuses_enforcement_bundle(tmp_path):
    path = tmp_path / "bad.joblib"
    _bundle(path, enforcement=True)
    try:
        MODULE.ShadowSequenceRuntime(path)
    except ValueError:
        return
    raise AssertionError("runtime accepted an enforcement-enabled bundle")


def test_runtime_emits_shadow_only_decision(tmp_path):
    path = tmp_path / "model.joblib"
    _bundle(path)
    result = MODULE.ShadowSequenceRuntime(path).evaluate(_events())
    assert result["shadow_decision"] in {"observe", "would_challenge"}
    assert result["enforcement_applied"] is False


def test_feature_contract_is_exact():
    assert set(MODULE.sequence_features(_events())) == set(MODULE.SEQUENCE_FEATURES)
