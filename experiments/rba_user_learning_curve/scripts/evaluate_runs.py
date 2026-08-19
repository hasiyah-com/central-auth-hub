#!/usr/bin/env python3
"""Train/evaluate every feature-ready run and update the combined CSV."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rba_experiment.evaluator import evaluate_run  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-id",
        action="append",
        help="Evaluate only this run_id; repeat the option for multiple runs.",
    )
    args = parser.parse_args()

    data_dir = ROOT / "data"
    combined_path = ROOT / "results" / "combined_run_results.csv"
    requested = set(args.run_id or [])
    run_dirs = sorted(
        path.parent
        for path in data_dir.glob("*/feature_snapshots.jsonl")
        if not requested or path.parent.name in requested
    )
    if requested - {path.name for path in run_dirs}:
        missing = sorted(requested - {path.name for path in run_dirs})
        raise SystemExit(f"feature-ready run not found: {', '.join(missing)}")
    if not run_dirs:
        raise SystemExit("no feature-ready runs found")

    for run_dir in run_dirs:
        result = evaluate_run(run_dir, combined_path)
        metrics = result["metrics"]
        print(
            f"{result['run_id']}: F1={metrics['f1']:.4f} "
            f"recall={metrics['recall']:.4f} FPR={metrics['fpr']:.4f}"
        )
    print(f"combined_results={combined_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
