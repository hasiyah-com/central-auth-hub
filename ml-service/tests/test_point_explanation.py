from pathlib import Path

import pytest

from app import l3_unified, model
from app.features import FEATURE_NAMES


def test_login_point_returns_all_real_shap_contributions(monkeypatch):
    monkeypatch.setattr(model, "MODEL_PATH", Path(__file__).parents[1] / "models/iforest_v1.pkl")
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
