from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rba_experiment.evaluator import _behavior_score, evaluate_run  # noqa: E402
from rba_experiment.feature_store import load_run_store  # noqa: E402
from rba_experiment.generator import generate_run, write_run  # noqa: E402
from rba_experiment.results import RESULT_COLUMNS  # noqa: E402

GIT_SHA = "c" * 40


class EvaluatorTests(unittest.TestCase):
    def test_new_device_is_not_double_counted_in_behavior_layer(self):
        history = [
            {"created_at": f"2024-01-0{day}T02:00:00Z"}
            for day in range(5, 10)
        ]
        event = {"created_at": "2024-01-10T02:00:00Z"}
        row = {
            "hours_from_typical_login_time": 0.0,
            "is_new_country": 0.0,
            "is_new_device": 1.0,
        }
        score, reasons = _behavior_score(row, event, history)
        self.assertEqual(score, 0.0)
        self.assertNotIn("behavior_new_device", reasons)

    def evaluate(self, root: Path, scenario: str):
        events, manifest = generate_run(
            dataset_size=10,
            seed=42,
            normal_scenario=scenario,
            git_commit_sha=GIT_SHA,
        )
        events_path, _ = write_run(events, manifest, root)
        load_run_store(events_path.parent)
        combined = root / "combined_run_results.csv"
        return evaluate_run(events_path.parent, combined), combined

    def test_fit_is_train_only_and_outputs_are_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            result, combined = self.evaluate(
                Path(directory), "normal_staggered"
            )
            self.assertEqual(result["prediction_count"], 264)
            metadata = json.loads(
                (result["model_path"].parent / "metadata.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(metadata["train_count"], 96)
            self.assertEqual(metadata["trained_on_label"], 0)
            self.assertEqual(metadata["max_samples_requested"], 256)
            self.assertEqual(metadata["max_samples_effective"], 96)

            predictions = [
                json.loads(line)
                for line in result["prediction_path"]
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(
                {item["split"] for item in predictions},
                {"normal_test", "attack_test"},
            )
            self.assertEqual(sum(item["label"] == 0 for item in predictions), 24)
            self.assertEqual(sum(item["label"] == 1 for item in predictions), 240)
            self.assertTrue(all(0 <= item["total_risk_score"] <= 1 for item in predictions))

            with combined.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(list(rows[0]), RESULT_COLUMNS)
            self.assertEqual(rows[0]["status"], "evaluated")
            self.assertNotEqual(rows[0]["f1"], "")

    def test_nat_burst_has_more_multi_account_rule_hits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staggered, _ = self.evaluate(root / "staggered", "normal_staggered")
            burst, _ = self.evaluate(root / "burst", "normal_nat_burst")

            def normal_multi_account_count(result):
                return sum(
                    item["label"] == 0
                    and "rule_multi_account_ip" in item["risk_reasons"]
                    for item in (
                        json.loads(line)
                        for line in result["prediction_path"]
                        .read_text(encoding="utf-8")
                        .splitlines()
                    )
                )

            self.assertEqual(normal_multi_account_count(staggered), 0)
            self.assertGreater(normal_multi_account_count(burst), 0)


if __name__ == "__main__":
    unittest.main()
