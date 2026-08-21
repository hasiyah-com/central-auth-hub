from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
from pathlib import Path

import joblib
import numpy as np


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
    tree = {
        "children_left": [1, -1, -1],
        "children_right": [2, -1, -1],
        "feature": [0, -2, -2],
        "threshold": [0.5, -2.0, -2.0],
        "probability_class_1": [0.5, 0.1, 0.9],
    }
    joblib.dump(
        {
            "version": "7-test",
            "model_format": MODULE.PORTABLE_MODEL_FORMAT,
            "portable_model": {"n_features": len(MODULE.SEQUENCE_FEATURES), "n_classes": 2, "trees": [tree]},
            "median": [0.0] * len(MODULE.SEQUENCE_FEATURES),
            "iqr": [1.0] * len(MODULE.SEQUENCE_FEATURES),
            "challenge_threshold": 0.5,
            "feature_names": MODULE.SEQUENCE_FEATURES,
            "enforcement_enabled": enforcement,
            "runtime_sklearn_required": False,
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


def test_committed_artifact_matches_manifest_and_loads():
    root = Path(__file__).resolve().parents[1]
    artifact_dir = root / "results" / "deployable_bundle_v7"
    manifest = json.loads((artifact_dir / "model_manifest_v7.json").read_text())
    for filename, expected_sha in manifest["files"].items():
        path = artifact_dir / filename
        assert path.stat().st_size == manifest["file_sizes"][filename]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha
    bundle = joblib.load(artifact_dir / "sequence_model_v7.joblib")
    assert bundle["model_format"] == MODULE.PORTABLE_MODEL_FORMAT
    assert bundle["runtime_sklearn_required"] is False
    assert "model" not in bundle
    MODULE.ShadowSequenceRuntime(artifact_dir / "sequence_model_v7.joblib")


def test_runtime_refuses_legacy_sklearn_bundle(tmp_path):
    path = tmp_path / "legacy.joblib"
    joblib.dump(
        {
            "version": "7-legacy",
            "model": object(),
            "median": [0.0] * len(MODULE.SEQUENCE_FEATURES),
            "iqr": [1.0] * len(MODULE.SEQUENCE_FEATURES),
            "challenge_threshold": 0.5,
            "feature_names": MODULE.SEQUENCE_FEATURES,
            "enforcement_enabled": False,
        },
        path,
    )
    try:
        MODULE.ShadowSequenceRuntime(path)
    except ValueError:
        return
    raise AssertionError("runtime accepted a legacy sklearn pickle bundle")
