"""โหลด + ใช้ Isolation Forest model.

decision_function ของ sklearn:
  ค่ามาก   = ปกติมาก (normal)
  ค่าน้อย  = ผิดปกติ (anomalous)
  ค่ารอบ 0 = ก้ำกึ่ง

แต่เราต้องการ "anomaly score" 0-1:
  0.0 = ปกติ
  1.0 = ผิดปกติมาก

แปลงด้วย sigmoid scaled
"""
import math
from pathlib import Path

import joblib
import numpy as np

MODEL_PATH = Path("/app/models/iforest_v1.pkl")

_model = None


def load_model():
    """โหลด model — cache ไว้หลังโหลดครั้งแรก."""
    global _model
    if _model is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"ไม่พบ model ที่ {MODEL_PATH} — รัน train_model ก่อน"
            )
        _model = joblib.load(MODEL_PATH)
    return _model


def model_loaded() -> bool:
    return MODEL_PATH.exists()


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
