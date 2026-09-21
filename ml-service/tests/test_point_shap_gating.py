"""SHAP ของ point view เฉพาะ login ที่ point score สูง — เขียนก่อน implementation (RED).

ที่มา: ML Capacity Gate §11 — SHAP ของ point view กินเวลา 16–18% ทุกระดับ · ปิดทั้งหมดแล้ว
reuseport 4 worker ผ่าน 4/4 แต่ hub ใช้ `point.explanation` เป็น `iforest_explanation`
(แท่ง SHAP ในหน้า ML, incident, audit) · ทางกลางที่เลือก (2026-09-22): คำนวณ SHAP เฉพาะเมื่อ
point score >= `POINT_ANOMALY` (0.50) — login ที่โมเดลเห็นว่าผิดปกติยังมีคำอธิบาย ส่วน login
ปกติไม่มี

- คะแนนต้องเท่าเดิมทุกกรณี (SHAP เป็นคำอธิบาย ไม่ใช่ตัวตัดสิน)
- ปรับเกณฑ์ได้ด้วย `L3_POINT_SHAP_MIN_SCORE` (0 = คำนวณทุก login แบบเดิม) · ค่าผิด = ไม่ start
- ตัวเลือกทดลอง `L3_EXPERIMENT_SKIP_POINT_SHAP=1` ยังข้ามทั้งหมดได้
"""

from __future__ import annotations

import pytest

from app import l3_unified as U
from app import model as M

FEATURES = [0.0] * U.FEATURE_COUNT
EXPL = [
    {"feature": "is_new_country", "shap": 0.2, "value": 1.0, "direction": "anomaly"}
]


@pytest.fixture
def fake(monkeypatch):
    state = {"score": 0.61, "explain_calls": 0, "score_calls": 0}

    def score_only(features):
        state["score_calls"] += 1
        return state["score"]

    def explain(features, top_k=5):
        state["explain_calls"] += 1
        return list(EXPL)

    monkeypatch.setattr(U, "predict_score", score_only)
    monkeypatch.setattr(U, "explain_features", explain)
    monkeypatch.delenv("L3_POINT_SHAP_MIN_SCORE", raising=False)
    monkeypatch.delenv("L3_EXPERIMENT_SKIP_POINT_SHAP", raising=False)
    return state


def test_high_score_login_gets_an_explanation(fake):
    out = U._point_view(FEATURES)
    assert fake["explain_calls"] == 1
    assert out["explanation"] == EXPL
    assert out["anomaly_score"] == 0.61


def test_low_score_login_skips_shap_but_keeps_the_score(fake):
    fake["score"] = 0.4053
    out = U._point_view(FEATURES)
    assert fake["explain_calls"] == 0
    assert out["explanation"] == []
    assert out["anomaly_score"] == 0.4053
    assert out["is_anomaly"] is False


def test_threshold_is_inclusive(fake):
    fake["score"] = U.POINT_ANOMALY
    U._point_view(FEATURES)
    assert fake["explain_calls"] == 1


def test_default_threshold_matches_point_anomaly():
    assert U.POINT_ANOMALY == 0.50
    assert U.point_shap_min_score() == U.POINT_ANOMALY


def test_zero_restores_the_old_behaviour(fake, monkeypatch):
    monkeypatch.setenv("L3_POINT_SHAP_MIN_SCORE", "0")
    fake["score"] = 0.01
    U._point_view(FEATURES)
    assert fake["explain_calls"] == 1


@pytest.mark.parametrize("bad", ["abc", "-0.1", "1.5", "nan"])
def test_invalid_threshold_is_refused(monkeypatch, bad):
    monkeypatch.setenv("L3_POINT_SHAP_MIN_SCORE", bad)
    with pytest.raises(ValueError, match="L3_POINT_SHAP_MIN_SCORE"):
        U.point_shap_min_score()


def test_startup_refuses_an_invalid_threshold(monkeypatch):
    pytest.importorskip("fastapi")
    from app import main

    monkeypatch.setattr(main, "load_model", lambda: None)
    monkeypatch.setattr(main, "warm_explainer", lambda: "ready")
    monkeypatch.setenv("L3_POINT_SHAP_MIN_SCORE", "abc")
    with pytest.raises(ValueError):
        main.startup()


def test_experiment_flag_still_skips_everything(fake, monkeypatch):
    monkeypatch.setenv("L3_EXPERIMENT_SKIP_POINT_SHAP", "1")
    U._point_view(FEATURES)
    assert fake["explain_calls"] == 0


def test_predict_with_explanation_is_unchanged(monkeypatch):
    """ฟังก์ชันเดิม (ใช้โดย /v1/score) = คะแนน + คำอธิบาย เหมือนเดิม."""
    monkeypatch.setattr(M, "predict_score", lambda f: 0.3)
    monkeypatch.setattr(M, "explain_features", lambda f, top_k=5: list(EXPL))
    assert M.predict_with_explanation(FEATURES, top_k=5) == (0.3, EXPL)


def test_capacity_stats_report_the_threshold(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from app import main

    monkeypatch.setenv("L3_CAPACITY_STATS", "1")
    monkeypatch.setenv("L3_POINT_SHAP_MIN_SCORE", "0.7")
    data = TestClient(main.app).get("/v1/l3-capacity-stats").json()["data"]
    assert data["point_shap_min_score"] == 0.7
