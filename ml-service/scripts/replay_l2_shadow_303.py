"""Aggregate-only bounded replay of historical legacy shadow risk scores."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

THRESHOLDS = {"warn": 0.50, "challenge": 0.70, "block": 0.85}


def _action(score: float) -> str:
    if score >= THRESHOLDS["block"]:
        return "block"
    if score >= THRESHOLDS["challenge"]:
        return "challenge"
    if score >= THRESHOLDS["warn"]:
        return "warn"
    return "allow"


def _prefixes(reasons: list[str]) -> set[str]:
    return {reason.split("=")[0].split(" (")[0].split(" ")[0] for reason in reasons}


def candidate(behavior: float, rule: float, iforest: float, reasons: list[str]):
    """Return adjusted raw scores and decision, preserving other evidence."""
    tags = _prefixes(reasons)
    time_diff = "hours_diff" in tags
    hour_rare = "hour_rarity" in tags
    temporal = time_diff or hour_rare
    score = behavior
    if time_diff and hour_rare:
        # Production weights: hours_diff +0.20/+0.40; hour_rarity +0.30.
        diff_weight = 0.40 if any(
            r.startswith("hours_diff=") and "(+0.40)" in r for r in reasons
        ) else 0.20
        score -= min(diff_weight, 0.30)
    l2_tags = tags & {
        "hours_diff", "hour_rarity", "weekend_mismatch", "is_new_country",
        "new_subsystem", "subsystem_rarity", "cadence_fast",
        "scope_escalation", "signature_rarity", "no_history",
    }
    independent_l2 = l2_tags - {
        "hours_diff", "hour_rarity", "weekend_mismatch", "no_history"
    }
    if "weekend_mismatch" in tags and (temporal or not independent_l2):
        score -= 0.10
    score = max(0.0, round(score, 4))
    total = min(1.0, round(rule + score + iforest, 4))
    decision = _action(total)
    new_subsystem = "new_subsystem" in tags
    if new_subsystem and decision in ("allow", "warn"):
        decision = "challenge"
    # No hard override for an existing independent L1/ML risk contribution.
    if decision == "block" and rule == 0.0 and iforest == 0.0 and not (
        independent_l2 - {"new_subsystem"}
    ):
        decision = "challenge"
    return score, total, decision


def run(path: Path) -> dict:
    counts = Counter()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        expected = {"risk_breakdown", "risk_reasons", "decision"}
        if not expected.issubset(rows.fieldnames or []):
            raise ValueError("historical replay schema is missing required fields")
        for row in rows:
            breakdown = json.loads(row["risk_breakdown"])
            reasons = json.loads(row["risk_reasons"])
            if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
                raise ValueError("risk reasons must be a string list")
            if not all(isinstance(breakdown.get(x), (int, float)) for x in (
                "rule", "behavior", "iforest"
            )):
                raise ValueError("recorded legacy raw scores are required")
            rule, behavior, iforest = (
                float(breakdown[x]) for x in ("rule", "behavior", "iforest")
            )
            old_total = min(1.0, round(rule + behavior + iforest, 4))
            old_band = _action(old_total)
            revised_behavior, new_total, new_action = candidate(
                behavior, rule, iforest, reasons
            )
            tags = _prefixes(reasons)
            counts["rows"] += 1
            counts[f"score_band_before_{old_band}"] += 1
            counts[f"score_band_after_{_action(new_total)}"] += 1
            counts[f"candidate_action_{new_action}"] += 1
            counts["behavior_score_decreased"] += revised_behavior < behavior
            counts["score_decreased"] += new_total < old_total
            counts["time_overlap"] += "hours_diff" in tags and "hour_rarity" in tags
            counts["weekend"] += "weekend_mismatch" in tags
            counts["new_subsystem"] += "new_subsystem" in tags
            old_recorded = row["decision"].removeprefix("would_")
            if row["decision"].startswith("would_"):
                counts["comparable_shadow_rows"] += 1
                counts[f"recorded_shadow_{old_recorded}"] += 1
                counts["recorded_matches_score_band"] += old_recorded == old_band
                counts[f"shadow_transition_{old_recorded}_to_{new_action}"] += 1
                counts["shadow_changed"] += old_recorded != new_action
            else:
                counts["non_shadow_outcome_rows"] += 1
    if counts["rows"] != 303:
        raise ValueError(f"expected exactly 303 rows, got {counts['rows']}")
    return {
        "status": "bounded_legacy_counterfactual_not_false_positive_validation",
        "holdout_opened": False,
        "no_expert_attack_labels": True,
        "counts": dict(sorted(counts.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.input)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, indent=2) + "\n")
    # Do not print any input data, identifiers or row-level reasons.
    print(json.dumps(result))


if __name__ == "__main__":
    main()
