"""สูตรคะแนน Isolation Forest ที่ใช้ร่วมกันระหว่าง service และ experiment."""

from __future__ import annotations

import numpy as np


def scores_with_model(model, features) -> list[float]:
    """แปลง ``decision_function`` เป็น anomaly score 0..1 แบบ production."""
    if len(features) == 0:
        return []
    raw = np.asarray(model.decision_function(np.asarray(features, dtype=float)))
    scaled = np.clip(raw * 5.0, -700.0, 700.0)
    scores = 1.0 / (1.0 + np.exp(scaled))
    return [max(0.0, min(1.0, float(x))) for x in scores]


def score_with_model(model, features) -> float:
    """เวอร์ชันหนึ่งเหตุการณ์ของ :func:`scores_with_model`."""
    return scores_with_model(model, [features])[0]
