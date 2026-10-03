"""Separate offline post-auth model: independently labeled five-minute windows only."""
from datetime import datetime
import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from scripts.compare_auth_context import split_users, evaluate
from point_scoring import scores_with_model

CONTRACT = "l3-post-auth-v1"
FEATURE_NAMES = ["post_requests_observed", "post_request_count_log1p",
                 "post_route_diversity_log1p", "post_write_fraction",
                 "post_error_fraction", "post_interval_log1p_mean"]


def read_dataset(path):
    meta = json.loads(path.with_suffix(path.suffix+".meta.json").read_text())
    if (meta.get("contract") != CONTRACT or meta.get("feature_names") != FEATURE_NAMES
        or meta.get("dataset_sha256") != hashlib.sha256(path.read_bytes()).hexdigest()):
        raise ValueError("post-auth checksum/contract mismatch")
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows or len({r["window"] for r in rows}) != len(rows):
        raise ValueError("empty/duplicate windows")
    if len({(r["subject"], r["from"], r["to"]) for r in rows}) != len(rows):
        raise ValueError("duplicate account windows")
    for row in rows:
        if row.get("label") not in (0, 1) or set(row["features"]) != set(FEATURE_NAMES):
            raise ValueError("independent window labels and exact features required")
        start, end = [datetime.fromisoformat(row[k].replace("Z", "+00:00")) for k in ["from", "to"]]
        if not start.tzinfo or not end.tzinfo or (end-start).total_seconds() != 300:
            raise ValueError("need timezone-aware five-minute windows")
    X = np.asarray([[r["features"][n] for n in FEATURE_NAMES] for r in rows], dtype=float)
    y = np.asarray([r["label"] for r in rows], dtype=int)
    ranges = [(0, 1), (0, np.log1p(10000)), (0, np.log1p(10000)),
              (0, 1), (0, 1), (0, np.log1p(300))]
    if not np.isfinite(X).all() or any(np.any((X[:, i] < lo) | (X[:, i] > hi))
                                     for i, (lo, hi) in enumerate(ranges)):
        raise ValueError("invalid post-auth feature values")
    return rows, X, y, meta


def train(path, output):
    rows, X, y, meta = read_dataset(path)
    tr, cal, test = split_users(rows)
    if sum(y[tr] == 0) < 20 or sum(y[cal] == 0) < 20 or set(y[test]) != {0, 1}:
        raise ValueError("insufficient normal training/calibration or mixed test labels")
    model = IsolationForest(n_estimators=100, contamination=.02, random_state=42,
                            max_samples=min(256, int(sum(y[tr] == 0))), n_jobs=-1)
    model.fit(X[tr][y[tr] == 0])
    model.rba_feature_contract_ = CONTRACT
    model.rba_feature_names_ = FEATURE_NAMES
    model.rba_training_provenance_ = meta
    cal_scores = np.asarray(scores_with_model(model, X[cal]))
    threshold = float(np.quantile(cal_scores[y[cal] == 0], .99, method="higher"))
    test_scores = np.asarray(scores_with_model(model, X[test]))
    output.mkdir(parents=True, exist_ok=True)
    artifact = output/"post_auth.candidate.pkl"
    joblib.dump(model, artifact)
    report = {"contract": CONTRACT, "activation": "offline_only; separate from login decisions",
              "dataset": meta, "model_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
              "threshold": threshold, "test": evaluate(y[test], test_scores, threshold),
              "split": {"train": tr.tolist(), "calibration": cal.tolist(), "test": test.tolist()},
              "scope": "disjoint-user holdout; Hub request windows only; not subsystem telemetry"}
    (output/"post_auth_validation.json").write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(train(args.data, args.output), indent=2))
