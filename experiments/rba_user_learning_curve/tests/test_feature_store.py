from __future__ import annotations

import csv
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rba_experiment.contracts import FEATURE_NAMES  # noqa: E402
from rba_experiment.feature_store import load_run_store  # noqa: E402
from rba_experiment.generator import generate_run, write_run  # noqa: E402
from rba_experiment.results import (  # noqa: E402
    RESULT_COLUMNS,
    feature_ready_result,
    upsert_combined_result,
)

GIT_SHA = "b" * 40


class FeatureStoreTests(unittest.TestCase):
    def build_run(self, root: Path, scenario: str):
        events, manifest = generate_run(
            dataset_size=10,
            seed=42,
            normal_scenario=scenario,
            git_commit_sha=GIT_SHA,
        )
        events_path, _ = write_run(events, manifest, root)
        return load_run_store(events_path.parent)

    def test_store_counts_feature_contract_and_privacy(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = self.build_run(Path(directory), "normal_staggered")
            self.assertEqual(summary["snapshot_count"], 360)
            self.assertEqual(summary["train_count"], 96)
            self.assertEqual(summary["normal_test_count"], 24)
            self.assertEqual(summary["attack_count"], 240)

            snapshots = [
                json.loads(line)
                for line in summary["feature_path"]
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            expected_keys = {
                "run_id",
                "event_id",
                "profile_id",
                "created_at",
                "split",
                "scenario",
                "ground_truth",
                "label",
                *FEATURE_NAMES,
            }
            self.assertEqual(set(snapshots[0]), expected_keys)
            for snapshot in snapshots:
                self.assertEqual(snapshot["is_thailand"], 1.0)
                self.assertEqual(snapshot["is_new_country"], 0.0)
                self.assertEqual(snapshot["country_change_count_30d"], 0.0)
                self.assertEqual(snapshot["impossible_travel_score"], 0.0)

            serialized = json.dumps(snapshots)
            for term in (
                "@" + "gmail.com",
                "@" + "pnu.ac.th",
                "user_id",
                "email",
            ):
                self.assertNotIn(term, serialized)

            connection = sqlite3.connect(summary["database_path"])
            try:
                counts = {
                    table: connection.execute(
                        f"SELECT COUNT(*) FROM {table}"  # nosec: test constants
                    ).fetchone()[0]
                    for table in ("raw_events", "feature_snapshots")
                }
                profile_count = connection.execute(
                    "SELECT COUNT(*) FROM profiles"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(counts, {"raw_events": 360, "feature_snapshots": 360})
            self.assertEqual(profile_count, 12)

    def test_attack_setup_actions_reach_expected_features(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = self.build_run(Path(directory), "normal_staggered")
            snapshots = [
                json.loads(line)
                for line in summary["feature_path"]
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            attacks = {}
            for snapshot in snapshots:
                if snapshot["ground_truth"] == "attack":
                    attacks.setdefault(snapshot["scenario"], snapshot)

            self.assertEqual(attacks["attack_new_device"]["is_new_device"], 1.0)
            self.assertEqual(
                attacks["attack_new_ua_family"]["is_new_user_agent_family"],
                1.0,
            )
            self.assertGreaterEqual(
                attacks["attack_failed_spike"]["failed_logins_24h"],
                5.0,
            )
            self.assertGreaterEqual(
                attacks["attack_login_velocity"]["login_count_24h"],
                5.0,
            )
            self.assertGreaterEqual(
                attacks["attack_concurrent_sessions"]["concurrent_session_count"],
                4.0,
            )
            self.assertEqual(
                attacks["attack_subsystem_lateral"]["active_subsystem_count"],
                2.0,
            )
            self.assertEqual(
                attacks["attack_new_passkey"]["new_passkey_recently_added"],
                1.0,
            )
            self.assertEqual(
                attacks["attack_permission_change"]["ever_changed_permission"],
                1.0,
            )
            self.assertGreaterEqual(
                attacks["attack_combined_ato"]["confirmed_incident_count"],
                1.0,
            )

    def test_combined_csv_upserts_one_row_per_run_without_metric_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summaries = [
                self.build_run(root, "normal_staggered"),
                self.build_run(root, "normal_nat_burst"),
            ]
            result_path = root / "combined_run_results.csv"
            for summary in summaries:
                row = feature_ready_result(summary)
                upsert_combined_result(result_path, row)
                upsert_combined_result(result_path, row)

            with result_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertEqual(list(rows[0]), RESULT_COLUMNS)

            evaluated = feature_ready_result(summaries[0])
            evaluated.update(
                {
                    "status": "evaluated",
                    "model_id": "iforest-test",
                    "tp": 100,
                    "fp": 2,
                    "tn": 22,
                    "fn": 140,
                    "precision": 0.98,
                    "recall": 0.4167,
                    "f1": 0.5848,
                    "roc_auc": 0.9,
                    "pr_auc": 0.8,
                    "fpr": 0.0833,
                    "allow_rate": 0.9167,
                    "mean_risk": 0.3,
                    "median_risk": 0.2,
                    "p90_risk": 0.7,
                    "p95_risk": 0.8,
                }
            )
            upsert_combined_result(result_path, evaluated)
            upsert_combined_result(
                result_path,
                feature_ready_result(summaries[0]),
            )
            with result_path.open(encoding="utf-8", newline="") as handle:
                by_run = {row["run_id"]: row for row in csv.DictReader(handle)}
            stored = by_run[evaluated["run_id"]]
            self.assertEqual(stored["status"], "evaluated")
            self.assertEqual(stored["model_id"], "iforest-test")
            self.assertEqual(stored["tp"], "100")


if __name__ == "__main__":
    unittest.main()
