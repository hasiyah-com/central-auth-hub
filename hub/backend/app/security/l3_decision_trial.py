"""Opt-in L3 access-decision trial using role percentiles and sequence evidence."""

from __future__ import annotations

REASON = "l3_percentile_decision_trial"


def apply(
    baseline_decision: str,
    percentile_result: dict | None,
    sequence_contract: dict | None,
    challenge_percentile: float,
) -> tuple[str, str | None, dict]:
    """Raise only an L1+L2 Allow; invalid/unavailable L3 evidence abstains."""
    detail = {
        "applied": False,
        "percentile": None,
        "warn_percentile": None,
        "challenge_percentile": challenge_percentile,
        "sequence_corroborated": False,
        "status": "skipped" if baseline_decision != "allow" else "abstain",
    }
    if baseline_decision != "allow" or not isinstance(percentile_result, dict):
        return baseline_decision, None, detail

    detail["status"] = percentile_result.get("status", "abstain")
    detail["percentile"] = percentile_result.get("percentile")
    detail["warn_percentile"] = percentile_result.get("warn_percentile")
    percentile = detail["percentile"]
    if detail["status"] not in {"normal", "warn"} or not isinstance(percentile, (int, float)):
        return baseline_decision, None, detail

    sequence_fired = bool(
        isinstance(sequence_contract, dict)
        and sequence_contract.get("monitoring_decision") == "l3_investigate"
    )
    detail["sequence_corroborated"] = sequence_fired
    warn_threshold = detail["warn_percentile"]
    warn_reached = (
        isinstance(warn_threshold, (int, float)) and percentile > warn_threshold
    )

    if percentile >= challenge_percentile or (warn_reached and sequence_fired):
        decision = "challenge"
    elif warn_reached:
        decision = "warn"
    else:
        return baseline_decision, None, detail

    detail["applied"] = True
    detail["decision"] = decision
    reason = (
        f"{REASON} (percentile={percentile:.4f}, "
        f"challenge={challenge_percentile:.4f}, sequence={sequence_fired})"
    )
    return decision, reason, detail
