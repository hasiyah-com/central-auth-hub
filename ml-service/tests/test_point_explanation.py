from pathlib import Path

import pytest
import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from app import l3_unified, model
from app.features import FEATURE_NAMES


def test_login_point_returns_all_real_shap_contributions(monkeypatch, tmp_path):
    forest = IsolationForest(n_estimators=10, random_state=42).fit(
        np.random.default_rng(42).normal(size=(100, 23)))
    forest.rba_feature_contract_ = model.FEATURE_CONTRACT
    path = tmp_path / "bangkok.pkl"
    joblib.dump(forest, path)
    monkeypatch.setattr(model, "MODEL_PATH", path)
    monkeypatch.setattr(model, "_model", None)
    monkeypatch.setattr(model, "_model_sha256", None)
    monkeypatch.setattr(model, "_explainer", None)
    monkeypatch.setattr(model, "_explainer_status", "uninitialized")
    features = [16, 4, 2.5, 1, 0, 0, 1, 1, 3, 1, 0, 1, 100, 0, 1, 1, 1, .8, .2, 0, 100, 0, 0]
    out = l3_unified.evaluate(None, "test-user", features, None, explain=False)
    point = out["point"]
    assert point["available"] is True
    assert point["explainer"] == "ready"
    assert point["anomaly_score"] == pytest.approx(model.predict_score(features), abs=0.00005)
    entries = point["explanation"]
    assert len(entries) == len(FEATURE_NAMES) == 23
    assert {entry["feature"] for entry in entries} == set(FEATURE_NAMES)
    assert [abs(entry["shap"]) for entry in entries] == sorted(
        (abs(entry["shap"]) for entry in entries), reverse=True
    )
    for entry in entries:
        assert entry["value"] == features[FEATURE_NAMES.index(entry["feature"])]


def test_missing_explainer_preserves_score_without_fabricating_contributions(monkeypatch):
    monkeypatch.setattr(model, "predict_score", lambda features: .57)
    monkeypatch.setattr(model, "_load_explainer", lambda: None)
    score, entries = model.predict_with_explanation([0.] * 23, top_k=23)
    assert score == .57
    assert entries == []


def test_startup_initializes_shap_and_reuses_it_for_requests(monkeypatch):
    class FakeExplainer:
        def shap_values(self, X):
            return np.ones_like(X)

    calls = []
    def initialize():
        calls.append(True)
        model._explainer = FakeExplainer()
        model._explainer_status = "ready"
        return model._explainer

    monkeypatch.setattr(model, "_explainer", None)
    monkeypatch.setattr(model, "_explainer_status", "uninitialized")
    monkeypatch.setattr(model, "predict_score", lambda _: .5)
    original_loader = model._load_explainer
    monkeypatch.setattr(model, "_load_explainer", initialize)
    assert model.warm_up_explainer() == "ready"
    monkeypatch.setattr(model, "_load_explainer", original_loader)
    assert len(model.predict_with_explanation([0.] * 23, top_k=23)[1]) == 23
    assert len(calls) == 1


def test_warmup_failure_preserves_unavailable_status(monkeypatch):
    monkeypatch.setattr(model, "_explainer_status", "unavailable")
    monkeypatch.setattr(model, "_explainer", None)
    assert model.warm_up_explainer() == "unavailable"


def test_service_startup_warms_shap_after_loading_model(monkeypatch):
    from app import main
    calls = []
    monkeypatch.setattr(main, "load_model", lambda: calls.append("model"))
    monkeypatch.setattr(main, "warm_up_explainer", lambda: calls.append("shap") or "ready")
    main.startup()
    assert calls == ["model", "shap"]
