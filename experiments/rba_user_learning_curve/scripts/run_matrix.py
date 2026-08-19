#!/usr/bin/env python3
"""Run or resume the complete RBA learning-curve experiment matrix."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT_ROOT / "src"))

from rba_experiment.matrix import run_matrix  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--git-commit-sha",
        default=os.environ.get("GIT_COMMIT_SHA"),
        help="40-character source commit SHA; may also use GIT_COMMIT_SHA",
    )
    parser.add_argument(
        "--dataset-size",
        dest="dataset_sizes",
        action="append",
        type=int,
        choices=[10, 50, 100, 500, 1000, 5000],
    )
    parser.add_argument(
        "--seed",
        dest="seeds",
        action="append",
        type=int,
        choices=[42, 43, 44, 45, 46],
    )
    parser.add_argument(
        "--normal-scenario",
        dest="normal_scenarios",
        action="append",
        choices=["normal_staggered", "normal_nat_burst"],
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="rebuild selected runs even when all outputs already exist",
    )
    args = parser.parse_args()
    if not args.git_commit_sha:
        parser.error("--git-commit-sha or GIT_COMMIT_SHA is required")

    outcomes = run_matrix(
        experiment_root=EXPERIMENT_ROOT,
        git_commit_sha=args.git_commit_sha,
        dataset_sizes=args.dataset_sizes,
        seeds=args.seeds,
        normal_scenarios=args.normal_scenarios,
        force=args.force,
    )
    evaluated = sum(item["status"] == "evaluated" for item in outcomes)
    skipped = sum(item["status"] == "skipped" for item in outcomes)
    print(f"matrix complete runs={len(outcomes)} evaluated={evaluated} skipped={skipped}")
    print(
        "combined_results="
        f"{EXPERIMENT_ROOT / 'results' / 'combined_run_results.csv'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
