"""Layer 3 — Isolation Forest Score Mapping: แปลง raw anomaly score → risk score.

อ้างอิง:
  - Liu, Ting, Zhou (2008) — Isolation Forest algorithm
  - Wiefling et al. (2022) — anomaly score interpretation
"""

from dataclasses import dataclass


@dataclass
class IForestResult:
    raw_score: float  # จาก ML Verifier (0.0–1.0)
    risk_score: float  # mapped risk contribution (0.0–0.4)
    label: str  # "high" / "medium" / "low" / "normal"


def map_score(raw_score: float) -> IForestResult:
    """Map IForest anomaly score → risk score contribution.

    | raw >= 0.7 → +0.40 (high anomaly)
    | raw >= 0.5 → +0.20 (medium)
    | raw >= 0.3 → +0.10 (low)
    | raw <  0.3 → +0.00 (normal)
    """
    if raw_score >= 0.7:
        return IForestResult(raw_score=raw_score, risk_score=0.40, label="high")
    elif raw_score >= 0.5:
        return IForestResult(raw_score=raw_score, risk_score=0.20, label="medium")
    elif raw_score >= 0.3:
        return IForestResult(raw_score=raw_score, risk_score=0.10, label="low")
    else:
        return IForestResult(raw_score=raw_score, risk_score=0.00, label="normal")
