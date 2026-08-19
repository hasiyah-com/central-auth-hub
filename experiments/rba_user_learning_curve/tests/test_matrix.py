from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rba_experiment.matrix import run_matrix  # noqa: E402

GIT_SHA = "d" * 40


class MatrixTests(unittest.TestCase):
    def test_matrix_completes_and_resumes_without_duplicate_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            experiment_root = Path(directory)
            messages: list[str] = []
            first = run_matrix(
                experiment_root=experiment_root,
                git_commit_sha=GIT_SHA,
                dataset_sizes=[10],
                seeds=[42],
                normal_scenarios=["normal_staggered"],
                progress=messages.append,
            )
            second = run_matrix(
                experiment_root=experiment_root,
                git_commit_sha=GIT_SHA,
                dataset_sizes=[10],
                seeds=[42],
                normal_scenarios=["normal_staggered"],
                progress=messages.append,
            )
            self.assertEqual(first[0]["status"], "evaluated")
            self.assertEqual(second[0]["status"], "skipped")
            with (
                experiment_root / "results" / "combined_run_results.csv"
            ).open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "evaluated")


if __name__ == "__main__":
    unittest.main()
