"""ตัวเลือกทดลอง: ข้าม SHAP ของ point view — เขียนก่อน implementation (RED).

ที่มา: ML Capacity Gate — reuseport 4 worker ผ่าน P1 ที่ c=20 แค่ 2 ใน 4 ครั้ง (185–255 ms)
SHAP ของ point view ใช้ ~1.7 ms จาก ~19 ms ต่อ request · ก่อนตัดสินใจเสียฟีเจอร์ ต้องวัดก่อนว่า
ได้คืนมาเท่าไร

**ห้ามใช้ใน production:** hub นำ `point.explanation` ไปเป็น `iforest_explanation`
(risk_engine.py:291) → บันทึกใน login_sessions (oauth/passkey) → แท่ง SHAP ในหน้า ML,
incident และ audit · ข้ามแล้วข้อมูลเหล่านี้จะว่างเงียบๆ (อาการแบบ B61)

จึงปิดไว้เป็นค่าเริ่มต้น เปิดด้วย `L3_EXPERIMENT_SKIP_POINT_SHAP=1` เท่านั้น และรายงานสถานะ
ใน `/v1/l3-capacity-stats` ให้ผลวัดตรวจย้อนได้ว่ารันโหมดไหน
"""

from __future__ import annotations

import pytest

from app import l3_unified as U

FEATURES = [0.0] * U.FEATURE_COUNT
EXPL = [{"feature": "hour_of_day", "shap": 0.2, "value": 3.0, "direction": "anomaly"}]


@pytest.fixture
def calls(monkeypatch):
    # คะแนน 0.61 >= เกณฑ์ SHAP (0.50) — ค่าเริ่มต้นจึงต้องคำนวณ SHAP
    seen = {"explain": 0, "score_only": 0}

    def explain(features, top_k=5):
        seen["explain"] += 1
        return list(EXPL)

    def score_only(features):
        seen["score_only"] += 1
        return 0.61

    monkeypatch.setattr(U, "explain_features", explain)
    monkeypatch.setattr(U, "predict_score", score_only)
    monkeypatch.delenv("L3_POINT_SHAP_MIN_SCORE", raising=False)
    return seen


def test_default_keeps_point_shap(calls, monkeypatch):
    monkeypatch.delenv("L3_EXPERIMENT_SKIP_POINT_SHAP", raising=False)
    out = U._point_view(FEATURES)
    assert calls["explain"] == 1 and calls["score_only"] == 1
    assert out["explanation"] == EXPL


def test_experiment_skips_shap_but_keeps_the_same_score(calls, monkeypatch):
    monkeypatch.setenv("L3_EXPERIMENT_SKIP_POINT_SHAP", "1")
    out = U._point_view(FEATURES)
    assert calls["explain"] == 0 and calls["score_only"] == 1
    assert out["explanation"] == []
    assert out["anomaly_score"] == 0.61
    assert out["is_anomaly"] is True  # 0.61 >= POINT_ANOMALY — ตัดสินเหมือนเดิม


@pytest.mark.parametrize("value", ["0", "", "true", "yes", "on"])
def test_only_the_exact_value_one_enables_the_experiment(calls, monkeypatch, value):
    """ค่าอื่นทั้งหมดต้องได้พฤติกรรมเดิม — กันเปิดโดยไม่ตั้งใจ."""
    monkeypatch.setenv("L3_EXPERIMENT_SKIP_POINT_SHAP", value)
    U._point_view(FEATURES)
    assert calls["explain"] == 1


def test_capacity_stats_report_the_mode(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from app import main

    monkeypatch.setenv("L3_CAPACITY_STATS", "1")
    client = TestClient(main.app)

    monkeypatch.delenv("L3_EXPERIMENT_SKIP_POINT_SHAP", raising=False)
    assert client.get("/v1/l3-capacity-stats").json()["data"]["point_shap"] is True
    monkeypatch.setenv("L3_EXPERIMENT_SKIP_POINT_SHAP", "1")
    assert client.get("/v1/l3-capacity-stats").json()["data"]["point_shap"] is False
