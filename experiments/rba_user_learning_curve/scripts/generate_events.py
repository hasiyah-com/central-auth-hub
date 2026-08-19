"""Generate one deterministic, alias-only RBA experiment run."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT_ROOT / "src"))

from rba_experiment.generator import generate_run, write_run  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-size",
        type=int,
        required=True,
        choices=[10, 50, 100, 500, 1000, 5000],
        help="normal events generated per profile",
    )
    parser.add_argument(
        "--seed",
        type=int,
        required=True,
        choices=[42, 43, 44, 45, 46],
    )
    parser.add_argument(
        "--normal-scenario",
        required=True,
        choices=["normal_staggered", "normal_nat_burst"],
        help="normal-network condition for this isolated run",
    )
    parser.add_argument(
        "--git-commit-sha",
        default=os.environ.get("GIT_COMMIT_SHA"),
        help="40-character source commit SHA; may also use GIT_COMMIT_SHA",
    )
    parser.add_argument(
        "--mapping",
        type=Path,
        default=EXPERIMENT_ROOT / "config" / "local_identity_mapping.json",
        help="ignored local identity mapping",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=EXPERIMENT_ROOT / "data",
        help="ignored directory for generated run data",
    )
    args = parser.parse_args()

    if not args.git_commit_sha:
        parser.error("--git-commit-sha or GIT_COMMIT_SHA is required")

    try:
        events, manifest = generate_run(
            dataset_size=args.dataset_size,
            seed=args.seed,
            normal_scenario=args.normal_scenario,
            git_commit_sha=args.git_commit_sha,
            mapping_path=args.mapping,
        )
        events_path, manifest_path = write_run(
            events,
            manifest,
            args.output_root,
        )
    except (AssertionError, KeyError, OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))

    normal_count = sum(event["ground_truth"] == "normal" for event in events)
    attack_count = len(events) - normal_count
    print(
        f"generated run={manifest['run_id']} normal={normal_count} "
        f"attack={attack_count}"
    )
    print(f"events={events_path}")
    print(f"manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
