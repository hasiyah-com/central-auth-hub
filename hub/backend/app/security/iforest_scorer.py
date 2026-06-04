"""Layer 3 — Isolation Forest Score Mapping: แปลง raw anomaly score → risk score.

อ้างอิง:
  - Liu, Ting, Zhou (2008) — Isolation Forest algorithm
  - Wiefling et al. (2022) — anomaly score interpretation
  - Lundberg & Lee (2017) — SHAP for tree ensembles (TreeSHAP)
"""

from dataclasses import dataclass, field


@dataclass
class IForestResult:
    raw_score: float  # จาก ML Verifier (0.0–1.0)
    risk_score: float  # mapped risk contribution (0.0–0.4)
    label: str  # "high" / "medium" / "low" / "normal"
    # SHAP explanation (top-k feature contributions) from ML service.
    # Each item: {feature: str, shap: float, value: float, direction: "anomaly"|"normal"}
    # Empty list when ML service is older or SHAP unavailable — Layer 1+2
    # reasons still cover the explainability story in that case.
    explanation: list[dict] = field(default_factory=list)


def map_score(raw_score: float, explanation: list[dict] | None = None) -> IForestResult:
    """Map IForest anomaly score → risk score contribution.

    | raw >= 0.7 → +0.40 (high anomaly)
    | raw >= 0.5 → +0.20 (medium)
    | raw >= 0.3 → +0.10 (low)
    | raw <  0.3 → +0.00 (normal)

    `explanation` is passed through unchanged — Layer 3 doesn't reshape it,
    just attaches it so downstream (audit log, UI) can show per-feature SHAP.
    """
    exp = explanation or []
    if raw_score >= 0.7:
        return IForestResult(
            raw_score=raw_score, risk_score=0.40, label="high", explanation=exp
        )
    elif raw_score >= 0.5:
        return IForestResult(
            raw_score=raw_score, risk_score=0.20, label="medium", explanation=exp
        )
    elif raw_score >= 0.3:
        return IForestResult(
            raw_score=raw_score, risk_score=0.10, label="low", explanation=exp
        )
    else:
        return IForestResult(
            raw_score=raw_score, risk_score=0.00, label="normal", explanation=exp
        )
