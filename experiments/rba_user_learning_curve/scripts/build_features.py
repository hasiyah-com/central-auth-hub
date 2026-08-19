"""Build isolated SQLite stores, feature snapshots, and one combined CSV."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT_ROOT / "src"))

from rba_experiment.feature_store import load_run_store  # noqa: E402
from rba_experiment.results import (  # noqa: E402
    feature_ready_result,
    upsert_combined_result,
)


def discover_runs(data_root: Path) -> list[Path]:
    return sorted(
        path
        for path in data_root.iterdir()
        if path.is_dir()
        and (path / "manifest.json").is_file()
        and (path / "events.jsonl").is_file()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "run_dirs",
        type=Path,
        nargs="*",
        help="run directories; omit to discover every generated run",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=EXPERIMENT_ROOT / "data",
    )
    parser.add_argument(
        "--combined-results",
        type=Path,
        default=EXPERIMENT_ROOT / "results" / "combined_run_results.csv",
    )
    args = parser.parse_args()

    run_dirs = args.run_dirs or discover_runs(args.data_root)
    if not run_dirs:
        parser.error("no generated runs found")

    for run_dir in run_dirs:
        try:
            summary = load_run_store(run_dir)
            upsert_combined_result(
                args.combined_results,
                feature_ready_result(summary),
            )
        except (AssertionError, KeyError, OSError, TypeError, ValueError) as exc:
            parser.error(f"{run_dir}: {exc}")
        print(
            f"features ready run={summary['manifest']['run_id']} "
            f"rows={summary['snapshot_count']} db={summary['database_path']}"
        )

    print(f"combined_results={args.combined_results}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
