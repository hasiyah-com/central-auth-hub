"""Upsert one row per experiment run into the combined CSV result file."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .contracts import FEATURE_NAMES

RESULT_COLUMNS = [
    "run_id",
    "status",
    "git_commit_sha",
    "normal_scenario",
    "dataset_size",
    "seed",
    "profile_count",
    "train_count",
    "normal_test_count",
    "attack_count",
    "feature_count",
    "model_id",
    "tp",
    "fp",
    "tn",
    "fn",
    "precision",
    "recall",
    "f1",
    "roc_auc",
    "pr_auc",
    "fpr",
    "allow_rate",
    "warn_plus_fpr",
    "warn_plus_recall",
    "challenge_plus_fpr",
    "challenge_plus_recall",
    "block_fpr",
    "block_recall",
    "allow_count",
    "warn_count",
    "challenge_count",
    "block_count",
    "mean_risk",
    "median_risk",
    "p90_risk",
    "p95_risk",
    "error",
]

STATUS_PRIORITY = {
    "generated": 0,
    "features_ready": 1,
    "trained": 2,
    "evaluated": 3,
    "failed": 4,
}


def empty_metric_fields() -> dict[str, Any]:
    return {
        "model_id": None,
        "tp": None,
        "fp": None,
        "tn": None,
        "fn": None,
        "precision": None,
        "recall": None,
        "f1": None,
        "roc_auc": None,
        "pr_auc": None,
        "fpr": None,
        "allow_rate": None,
        "warn_plus_fpr": None,
        "warn_plus_recall": None,
        "challenge_plus_fpr": None,
        "challenge_plus_recall": None,
        "block_fpr": None,
        "block_recall": None,
        "allow_count": None,
        "warn_count": None,
        "challenge_count": None,
        "block_count": None,
        "mean_risk": None,
        "median_risk": None,
        "p90_risk": None,
        "p95_risk": None,
    }


def feature_ready_result(summary: dict[str, Any]) -> dict[str, Any]:
    manifest = summary["manifest"]
    return {
        "run_id": manifest["run_id"],
        "status": "features_ready",
        "git_commit_sha": manifest["git_commit_sha"],
        "normal_scenario": manifest["normal_scenario"],
        "dataset_size": manifest["dataset_size"],
        "seed": manifest["seed"],
        "profile_count": 12,
        "train_count": summary["train_count"],
        "normal_test_count": summary["normal_test_count"],
        "attack_count": summary["attack_count"],
        "feature_count": len(FEATURE_NAMES),
        **empty_metric_fields(),
        "error": "",
    }


def _read_rows(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        unknown = set(fieldnames) - set(RESULT_COLUMNS)
        if unknown:
            raise ValueError(
                f"combined result CSV has unknown columns: {sorted(unknown)}"
            )
        rows = {}
        for row in reader:
            rows[row["run_id"]] = {
                column: row.get(column, "") for column in RESULT_COLUMNS
            }
        return rows


def _merge_row(
    previous: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    unknown = set(incoming) - set(RESULT_COLUMNS)
    if unknown:
        raise ValueError(f"unknown combined result fields: {sorted(unknown)}")
    if set(RESULT_COLUMNS) - set(incoming):
        raise ValueError("combined result row must contain every contract column")

    if previous is None:
        return dict(incoming)

    merged = dict(previous)
    for key, value in incoming.items():
        if value is not None and value != "":
            merged[key] = value
    previous_status = previous.get("status", "generated")
    incoming_status = incoming["status"]
    if STATUS_PRIORITY[incoming_status] < STATUS_PRIORITY.get(previous_status, 0):
        merged["status"] = previous_status
    return merged


def upsert_combined_result(path: Path, row: dict[str, Any]) -> None:
    """Atomically insert or update a run without creating duplicate run_id rows."""
    rows = _read_rows(path)
    rows[row["run_id"]] = _merge_row(rows.get(row["run_id"]), row)
    ordered = sorted(
        rows.values(),
        key=lambda item: (
            item["normal_scenario"],
            int(item["dataset_size"]),
            int(item["seed"]),
        ),
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        for item in ordered:
            writer.writerow(
                {
                    key: "" if item.get(key) is None else item.get(key)
                    for key in RESULT_COLUMNS
                }
            )
    temporary.replace(path)
