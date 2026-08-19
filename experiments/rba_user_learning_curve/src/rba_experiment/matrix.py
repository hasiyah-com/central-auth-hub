"""Resumable end-to-end runner for the complete experiment matrix."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable

from .contracts import load_config
from .evaluator import evaluate_run
from .feature_store import load_run_store
from .generator import generate_run, write_run
from .results import feature_ready_result, upsert_combined_result


def _evaluated_run_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            row["run_id"]
            for row in csv.DictReader(handle)
            if row.get("status") == "evaluated"
        }


def run_matrix(
    *,
    experiment_root: Path,
    git_commit_sha: str,
    dataset_sizes: list[int] | None = None,
    seeds: list[int] | None = None,
    normal_scenarios: list[str] | None = None,
    force: bool = False,
    progress: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Run every selected cell and resume only from incomplete stages."""
    config = load_config("experiment")
    sizes = dataset_sizes or config["dataset_sizes_per_user"]
    selected_seeds = seeds or config["seeds"]
    scenarios = normal_scenarios or config["normal_scenarios"]
    data_root = experiment_root / "data"
    combined_path = experiment_root / "results" / "combined_run_results.csv"
    data_root.mkdir(parents=True, exist_ok=True)
    completed = _evaluated_run_ids(combined_path)
    outcomes: list[dict[str, Any]] = []
    total = len(sizes) * len(selected_seeds) * len(scenarios)
    ordinal = 0

    for dataset_size in sizes:
        for seed in selected_seeds:
            for normal_scenario in scenarios:
                ordinal += 1
                run_id = (
                    f"{config['experiment_id']}-{normal_scenario}-"
                    f"n{dataset_size}-s{seed}"
                )
                run_dir = data_root / run_id
                manifest_path = run_dir / "manifest.json"
                events_path = run_dir / "events.jsonl"
                existing_manifest = None
                if manifest_path.exists():
                    existing_manifest = json.loads(
                        manifest_path.read_text(encoding="utf-8")
                    )
                regenerate = (
                    force
                    or not events_path.exists()
                    or existing_manifest is None
                    or existing_manifest.get("git_commit_sha") != git_commit_sha
                )
                progress(f"[{ordinal}/{total}] {run_id}")

                if regenerate:
                    events, manifest = generate_run(
                        dataset_size=dataset_size,
                        seed=seed,
                        normal_scenario=normal_scenario,
                        git_commit_sha=git_commit_sha,
                    )
                    write_run(events, manifest, data_root)
                    progress(f"  generated rows={len(events)}")

                feature_path = run_dir / "feature_snapshots.jsonl"
                database_path = run_dir / "experiment.sqlite3"
                rebuild_features = regenerate or not (
                    feature_path.exists() and database_path.exists()
                )
                if rebuild_features:
                    summary = load_run_store(run_dir)
                    upsert_combined_result(
                        combined_path,
                        feature_ready_result(summary),
                    )
                    progress(f"  features rows={summary['snapshot_count']}")

                required_outputs = (
                    run_dir / "model" / "iforest.pkl",
                    run_dir / "model" / "metadata.json",
                    run_dir / "predictions.jsonl",
                    run_dir / "metrics.json",
                )
                reevaluate = (
                    regenerate
                    or rebuild_features
                    or run_id not in completed
                    or not all(path.exists() for path in required_outputs)
                )
                if reevaluate:
                    result = evaluate_run(run_dir, combined_path)
                    completed.add(run_id)
                    progress(
                        "  evaluated "
                        f"F1={result['metrics']['f1']:.4f} "
                        f"FPR={result['metrics']['fpr']:.4f}"
                    )
                    outcomes.append(
                        {"run_id": run_id, "status": "evaluated", **result}
                    )
                else:
                    metrics = json.loads(
                        (run_dir / "metrics.json").read_text(encoding="utf-8")
                    )
                    progress("  skipped complete run")
                    outcomes.append(
                        {"run_id": run_id, "status": "skipped", "metrics": metrics}
                    )

    return outcomes
