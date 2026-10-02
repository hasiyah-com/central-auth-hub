"""Build role percentiles from held-out benign scores; does not activate them."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.security.l3_percentile_fallback import ROLES, build_artifact


def build_from_records(data, thresholds, dataset_sha256):
    if data.get("split") != "validation-calibration":
        raise ValueError("only independent validation-calibration split allowed")
    samples = {r: [] for r in ROLES}
    skipped = 0
    model_hash = data["model_sha256"]
    for row in data["records"]:
        if row.get("is_attack") is not True and row.get("is_attack") is not False:
            raise ValueError("explicit independent ground-truth label required")
        if row.get("model_sha256") != model_hash:
            raise ValueError("mixed model scores are not allowed")
        if row["is_attack"] or row.get("baseline_decision") != "allow":
            skipped += 1
            continue
        role = row["user_type"]
        if role not in samples:
            raise ValueError("unknown user type")
        samples[role].append(row["score"])
    result = build_artifact(
        samples,
        thresholds,
        model_sha256=model_hash,
        provenance={
            "split": data["split"],
            "dataset_sha256": dataset_sha256,
            "score_source": "l3-evaluate.point.anomaly_score",
            "conditioning": "L1+L2 allow; independently benign",
        },
    )
    result["skipped_records"] = skipped
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--thresholds",
        required=True,
        help="JSON mapping all four roles to percentile thresholds 0.5..1",
    )
    args = parser.parse_args()
    content = args.input.read_bytes()
    result = build_from_records(
        json.loads(content),
        json.loads(args.thresholds),
        hashlib.sha256(content).hexdigest(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2, allow_nan=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
