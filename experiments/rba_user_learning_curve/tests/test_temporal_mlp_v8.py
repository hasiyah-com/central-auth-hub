from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_temporal_mlp_v8.py"
RUNTIME_SCRIPT = ROOT / "scripts" / "shadow_temporal_runtime_v8.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V8 = _load("temporal_mlp_v8_test", SCRIPT)
RUNTIME = _load("shadow_temporal_runtime_v8_test", RUNTIME_SCRIPT)


def test_v8_is_standalone_and_has_no_random_forest():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "RandomForestClassifier" not in source
    assert "from sklearn.ensemble" not in source
    assert "import sklearn.ensemble" not in source
    assert "run_supervised_sequence_v6" not in source
    assert "run_sequence_model_v5" not in source
    assert "importlib" not in source
    assert V8.RULE_FEATURES
    assert V8.BEHAVIOR_FEATURES
    assert V8.NEURAL_EVENT_FEATURES


def test_feature_ownership_is_disjoint():
    rule = set(V8.RULE_FEATURES)
    behavior = set(V8.BEHAVIOR_FEATURES)
    neural = set(V8.NEURAL_EVENT_FEATURES)
    assert rule.isdisjoint(behavior)
    assert rule.isdisjoint(neural)
    assert behavior.isdisjoint(neural)


@pytest.mark.parametrize("scenario", V8.SCENARIOS)
def test_normal_generator_rebuilds_80_20_timeline(scenario):
    users = V8._load_users()
    rows = V8.generate_normal(users, 10, 42, scenario)
    assert len(rows) == 120
    grouped = V8._profile_events(rows)
    for events in grouped.values():
        assert sum(event.split == "train" for event in events) == 8
        assert sum(event.split == "normal_test" for event in events) == 2
        assert max(event.failed_1h for event in events) < 3
        assert max(event.success_10m for event in events) < 5
        assert max(event.concurrent_sessions for event in events) < 4
        assert all(left.timestamp <= right.timestamp for left, right in zip(events, events[1:]))


def test_attack_train_validation_test_are_disjoint_and_below_rule_floors():
    users = V8._load_users()
    normal = V8.generate_normal(users, 50, 42, "normal_nat_burst")
    trusted = [event for event in normal if event.split == "train"]
    groups = [
        V8.generate_attacks(users, trusted, 42 + offset, "normal_nat_burst", subtlety)
        for offset, subtlety in (
            (V8.TRAIN_ATTACK_OFFSET, 1.0),
            (V8.VALIDATION_ATTACK_OFFSET, 0.88),
            (V8.TEST_ATTACK_OFFSET, 0.72),
        )
    ]
    ids = [{phase.sequence_id for phase in phases} for phases in groups]
    assert ids[0].isdisjoint(ids[1])
    assert ids[0].isdisjoint(ids[2])
    assert ids[1].isdisjoint(ids[2])
    for phases in groups:
        assert phases
        assert max(phase.event.failed_1h for phase in phases) < 3
        assert max(phase.event.success_10m for phase in phases) < 5
        assert max(phase.event.concurrent_sessions for phase in phases) < 4
        assert all(phase.event.new_passkey == 0 for phase in phases)
        assert all(phase.event.confirmed_incident == 0 for phase in phases)


def test_portable_artifact_loads_without_pickle_and_matches_direct_probability():
    bundle = V8.RESULTS_DIR
    runtime = RUNTIME.load_runtime(bundle)
    contract = json.loads((bundle / "model_contract_v8.json").read_text(encoding="utf-8"))
    assert contract["random_forest"] is False
    assert contract["imports_previous_experiment_code"] is False
    assert contract["artifact"]["requires_sklearn_runtime"] is False
    vector = np.linspace(-1.0, 1.0, V8.NEURAL_INPUT_SIZE)
    direct = V8._sigmoid(
        np.tanh(
            np.tanh(
                np.clip((vector - runtime.input_median) / runtime.input_iqr, -10.0, 10.0)
                @ runtime.weights[0]
                + runtime.biases[0]
            )
            @ runtime.weights[1]
            + runtime.biases[1]
        )
        @ runtime.weights[2]
        + runtime.biases[2]
    ).reshape(-1)[0]
    assert RUNTIME.probability(runtime, vector) == pytest.approx(float(direct), abs=1e-14)


def test_runtime_abstains_for_cold_profile_and_never_enforces():
    runtime = RUNTIME.load_runtime(V8.RESULTS_DIR)
    vector = np.zeros(V8.NEURAL_INPUT_SIZE)
    cold = RUNTIME.score_shadow(runtime, vector, V8.SHADOW_MIN_TRUSTED_EVENTS - 1)
    mature = RUNTIME.score_shadow(runtime, vector, V8.SHADOW_MIN_TRUSTED_EVENTS)
    assert cold["decision"] == "shadow_abstain_cold_profile"
    assert cold["probability"] is None
    assert cold["enforce"] is False
    assert mature["decision"].startswith("would_")
    assert mature["enforce"] is False


def test_runtime_rejects_corrupt_artifact(tmp_path):
    for name in ("model_contract_v8.json", "temporal_mlp_v8.npz"):
        shutil.copy2(V8.RESULTS_DIR / name, tmp_path / name)
    artifact = tmp_path / "temporal_mlp_v8.npz"
    payload = bytearray(artifact.read_bytes())
    payload[len(payload) // 2] ^= 0x01
    artifact.write_bytes(payload)
    with pytest.raises(ValueError, match="checksum mismatch"):
        RUNTIME.load_runtime(tmp_path)


def test_committed_gate_is_shadow_only_and_has_history_guard():
    gate = json.loads((V8.RESULTS_DIR / "release_gate.json").read_text(encoding="utf-8"))
    assert gate["ready_for_enforcement"] is False
    assert gate["shadow_activation"]["minimum_trusted_events"] == 1000
    assert gate["checks"]["random_forest_absent"] is True
    assert gate["checks"]["standalone_pipeline"] is True
