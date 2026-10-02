"""Paired L1+L2 vs role-percentile fallback evaluation on independent labeled scores."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.security.l3_percentile_fallback import ROLES, evaluate, validate_artifact


def compare_records(artifact, data):
    validate_artifact(artifact)
    if data.get("split") != "validation-evaluation":
        raise ValueError("separate validation-evaluation split required")
    results = {}
    for role in ROLES:
        rows = [r for r in data["records"] if r["user_type"] == role]
        counts = {
            "n_normal": 0,
            "n_attack": 0,
            "baseline_warn_normal": 0,
            "fallback_warn_normal": 0,
            "baseline_detected_attack": 0,
            "fallback_detected_attack": 0,
            "baseline_challenged_attack": 0,
            "challenged_normal": 0,
            "blocked_normal": 0,
            "abstained": 0,
        }
        for row in rows:
            if row.get("is_attack") is not True and row.get("is_attack") is not False:
                raise ValueError("independent attack label required")
            baseline = row["baseline_decision"]
            if baseline not in ("allow", "warn", "challenge", "block"):
                raise ValueError("explicit baseline access decision required")
            result = evaluate(
                artifact,
                baseline,
                role,
                row["score"],
                row["model_sha256"],
                validated=True,
            )
            warning = result["status"] == "warn"
            counts["abstained"] += result["status"] == "abstain"
            if row["is_attack"]:
                counts["n_attack"] += 1
                counts["baseline_detected_attack"] += baseline != "allow"
                counts["fallback_detected_attack"] += baseline != "allow" or warning
                counts["baseline_challenged_attack"] += baseline in (
                    "challenge",
                    "block",
                )
            else:
                counts["n_normal"] += 1
                counts["baseline_warn_normal"] += baseline == "warn"
                counts["fallback_warn_normal"] += baseline == "warn" or warning
                counts["challenged_normal"] += baseline in ("challenge", "block")
                counts["blocked_normal"] += baseline == "block"

        def rate(k, n, counts=counts):
            return counts[k] / counts[n] if counts[n] else None

        results[role] = {
            **counts,
            "baseline_recall_warn_plus": rate("baseline_detected_attack", "n_attack"),
            "fallback_recall_warn_plus": rate("fallback_detected_attack", "n_attack"),
            "recall_challenge_unchanged": rate(
                "baseline_challenged_attack", "n_attack"
            ),
            "baseline_warn_fpr": rate("baseline_warn_normal", "n_normal"),
            "fallback_warn_fpr": rate("fallback_warn_normal", "n_normal"),
            "challenge_fpr_unchanged": rate("challenged_normal", "n_normal"),
            "block_fpr_unchanged": rate("blocked_normal", "n_normal"),
        }
    if any(r["user_type"] not in ROLES for r in data["records"]):
        raise ValueError("unknown role")
    return {
        "per_role": results,
        "split": data["split"],
        "deploy_ready": False,
        "note": "Paired point estimates; independent user-cluster confidence intervals still required.",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--calibration", type=Path, required=True)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = compare_records(
        json.loads(a.calibration.read_text()), json.loads(a.input.read_text())
    )
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("x") as f:
        json.dump(result, f, indent=2, allow_nan=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
