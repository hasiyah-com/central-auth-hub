"""Distinct prior countries must mean the same thing in synthetic and runtime data."""
import hashlib
import importlib.util
import json
from pathlib import Path
import random

import pytest


@pytest.fixture(autouse=True)
def preserve_random_state():
    state = random.getstate()
    yield
    random.setstate(state)


def load_generator(monkeypatch, tmp_path, mode):
    monkeypatch.setenv("RBA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RBA_COUNTRY_COUNT_MODE", mode)
    source = Path(__file__).parents[1] / "scripts" / "generate_data.py"
    spec = importlib.util.spec_from_file_location("country_test_generator", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample(module):
    random.seed(42)
    return [module.normal_session() for _ in range(100)] + [module.anomaly_session() for _ in range(100)]


def test_normal_with_known_country_history_has_at_least_one_country(monkeypatch, tmp_path):
    module = load_generator(monkeypatch, tmp_path, "distinct-v1")
    rows = [module.normal_session() for _ in range(1000)]
    assert all(row[5] >= 1 for row in rows)
    assert {row[5] for row in rows} == {1, 2}


def test_only_country_count_changes_with_same_random_stream(monkeypatch, tmp_path):
    legacy = sample(load_generator(monkeypatch, tmp_path, "legacy-v0"))
    corrected = sample(load_generator(monkeypatch, tmp_path, "distinct-v1"))
    assert any(a[5] != b[5] for a, b in zip(legacy, corrected))
    for a, b in zip(legacy, corrected):
        assert len(a) == len(b) == 23
        assert a[:5] + a[6:] == b[:5] + b[6:]
        assert b[5] >= 1


def test_invalid_mode_rejected(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="RBA_COUNTRY_COUNT_MODE"):
        load_generator(monkeypatch, tmp_path, "typo")


def test_legacy_mode_reproduces_pre_fix_vectors(monkeypatch, tmp_path):
    rows = sample(load_generator(monkeypatch, tmp_path, "legacy-v0"))
    digest = hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()
    assert digest == "e47e3af758941396d900c5603d42da946f2308a8ed2110691536e093fba346b6"


@pytest.mark.parametrize("mode,semantics", [
    ("distinct-v1", "distinct_observed_countries"),
    ("legacy-v0", "legacy_mixed_country_semantics"),
])
def test_metadata_identifies_country_semantics(monkeypatch, tmp_path, mode, semantics):
    module = load_generator(monkeypatch, tmp_path, mode)
    module.NORMAL_COUNT, module.ANOMALY_COUNT = 5, 2
    module.main()
    meta = json.loads(module.OUTPUT.with_suffix(".csv.meta.json").read_text())
    assert meta["country_count_mode"] == mode
    assert meta["country_count_semantics"] == semantics
    assert meta["dataset_sha256"] == hashlib.sha256(module.OUTPUT.read_bytes()).hexdigest()
