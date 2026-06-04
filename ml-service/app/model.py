"""โหลด + ใช้ Isolation Forest model — พร้อม SHAP explainability.

decision_function ของ sklearn:
  ค่ามาก   = ปกติมาก (normal)
  ค่าน้อย  = ผิดปกติ (anomalous)
  ค่ารอบ 0 = ก้ำกึ่ง

แต่เราต้องการ "anomaly score" 0-1:
  0.0 = ปกติ
  1.0 = ผิดปกติมาก

แปลงด้วย sigmoid scaled.

SHAP convention (สำคัญ — มี sign flip):
  shap_value บน decision_function:
    > 0  → feature ผลัก output ทาง NORMAL
    < 0  → feature ผลัก output ทาง ANOMALY
  เราต้องการ UI ที่ "positive = anomalous" (intuitive กว่า)
  → flip sign: anomaly_contribution = -shap_value
"""

import logging
import math
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from app.features import FEATURE_NAMES

log = logging.getLogger(__name__)

MODEL_PATH = Path("/app/models/iforest_v1.pkl")

_model = None
_explainer: Any = None  # shap.TreeExplainer | None — typed Any to avoid import cost when SHAP unavailable
_explainer_status: str = "uninitialized"  # "ready" | "unavailable" | "uninitialized"


def load_model():
    """โหลด model — cache ไว้หลังโหลดครั้งแรก."""
    global _model
    if _model is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"ไม่พบ model ที่ {MODEL_PATH} — รัน train_model ก่อน")
        _model = joblib.load(MODEL_PATH)
    return _model


def model_loaded() -> bool:
    return MODEL_PATH.exists()


def _load_explainer():
    """Lazy-init SHAP TreeExplainer (called on first explain call).

    Fail-safe: ถ้า shap import พัง หรือ TreeExplainer ไม่รองรับ IForest ของ
    sklearn version นี้ → ตั้ง status เป็น 'unavailable' แล้วใช้ fallback
    (top-3 feature deviation จาก feature_extraction normalization).

    ใช้ `feature_perturbation="tree_path_dependent"` — ไม่ต้อง background
    dataset, เร็วกว่า, และทำงานกับ IsolationForest โดยตรง.
    """
    global _explainer, _explainer_status

    if _explainer_status != "uninitialized":
        return _explainer

    try:
        import shap

        model = load_model()
        _explainer = shap.TreeExplainer(
            model,
            feature_perturbation="tree_path_dependent",
        )
        _explainer_status = "ready"
        log.info("SHAP TreeExplainer ready (IsolationForest)")
    except Exception as e:
        _explainer = None
        _explainer_status = "unavailable"
        log.warning(
            "SHAP TreeExplainer unavailable — falling back to heuristic. " "Reason: %s",
            e,
        )

    return _explainer


def explainer_status() -> str:
    """For /health debug — บอกว่า explainer พร้อมไหม."""
    return _explainer_status


def predict_score(features: list[float]) -> float:
    """คืนค่า anomaly score 0.0 (ปกติ) - 1.0 (ผิดปกติ).

    ใช้ sigmoid ของ -decision_function เพื่อให้:
      raw > 0 (normal)   -> score < 0.5
      raw = 0 (borderline) -> score = 0.5
      raw < 0 (anomaly)  -> score > 0.5
    """
    model = load_model()
    X = np.array([features], dtype=float)
    raw = float(model.decision_function(X)[0])
    # scaled sigmoid: เน้นกราฟชันแถวๆ 0 ทำให้ score แยกชัดขึ้น
    score = 1.0 / (1.0 + math.exp(raw * 5.0))
    return max(0.0, min(1.0, score))


def predict_with_explanation(
    features: list[float],
    top_k: int = 5,
) -> tuple[float, list[dict]]:
    """คืน (score, top_k feature contributions) — main entry สำหรับ /v1/score.

    Returns:
      score: 0.0-1.0 (เหมือน predict_score เดิม)
      explanation: list of dict ใน format
        [
          {
            "feature": "is_new_country",
            "shap": 0.18,           # anomaly contribution (positive = anomaly)
            "value": 1.0,            # input feature value
            "direction": "anomaly",  # "anomaly" | "normal"
          },
          ...
        ]
        เรียงตาม |shap| descending, สูงสุด top_k

    ถ้า explainer unavailable → คืน explanation=[] (fail-safe, Hub ทำงานต่อได้)
    """
    score = predict_score(features)
    explainer = _load_explainer()

    if explainer is None:
        return score, []

    try:
        X = np.array([features], dtype=float)
        # shap_values shape: (n_samples, n_features) สำหรับ IForest
        raw_shap = explainer.shap_values(X)
        # Handle case where shap_values returns a list (multi-output) or array
        if isinstance(raw_shap, list):
            raw_shap = raw_shap[0]
        shap_per_feat = raw_shap[0]  # ดึง row แรก (sample เดียว)

        # Sign flip — เราต้องการ "positive = anomaly"
        anomaly_contrib = -shap_per_feat

        # Top-k by |contribution|
        indexed = sorted(
            enumerate(anomaly_contrib),
            key=lambda x: abs(float(x[1])),
            reverse=True,
        )[:top_k]

        explanation = [
            {
                "feature": FEATURE_NAMES[i],
                "shap": round(float(val), 4),
                "value": round(float(features[i]), 4),
                "direction": "anomaly" if float(val) > 0 else "normal",
            }
            for i, val in indexed
        ]
        return score, explanation
    except Exception as e:
        # Fail-safe — log warning + คืน [] (Hub ทำงานต่อได้แม้ explain พัง)
        log.warning(
            "SHAP explain failed for one sample — returning empty. Reason: %s", e
        )
        return score, []
