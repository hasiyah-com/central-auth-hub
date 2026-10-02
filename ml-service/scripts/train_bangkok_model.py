"""Train a staged Bangkok model with independent train/calibration/test splits.

python -m scripts.train_bangkok_model --data PATH --output DIR
Never replaces the production artifact automatically.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score

from app.features import FEATURE_CONTRACT, FEATURE_NAMES, FEATURE_RANGES
from point_scoring import scores_with_model


def read_dataset(path):
    meta = json.loads(path.with_suffix(".csv.meta.json").read_text())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if (meta.get("feature_contract") != FEATURE_CONTRACT
        or meta.get("timezone") != "Asia/Bangkok"
        or meta.get("dataset_sha256") != digest):
        raise ValueError("dataset contract/timezone/checksum mismatch; re-export source timestamps")
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FEATURE_NAMES + ["label"]:
            raise ValueError("feature names/order mismatch")
        rows = list(reader)
    X = np.array([[float(r[n]) for n in FEATURE_NAMES] for r in rows])
    y = np.array([int(r["label"]) for r in rows])
    if not len(X) or not np.isfinite(X).all() or not set(y) <= {0, 1}:
        raise ValueError("invalid samples/labels")
    for i, name in enumerate(FEATURE_NAMES):
        lo, hi = FEATURE_RANGES[name]
        if np.any((X[:, i] < lo) | (X[:, i] > hi)):
            raise ValueError(f"feature out of range: {name}")
    return X, y, meta


def metrics(y, scores, threshold):
    flagged = scores > threshold
    return {"fpr": float(flagged[y == 0].mean()),
        "recall": float(flagged[y == 1].mean()),
        "normal": int((y == 0).sum()), "attack": int((y == 1).sum())}


def train(path, output):
    X, y, meta = read_dataset(path)
    indices = np.arange(len(y))
    tr, rest = train_test_split(indices, test_size=.4, stratify=y, random_state=42)
    cal, test = train_test_split(rest, test_size=.5, stratify=y[rest], random_state=43)
    model = IsolationForest(n_estimators=100, contamination=.02,
        max_samples=256, random_state=42, n_jobs=-1)
    model.fit(X[tr][y[tr] == 0])
    model.rba_feature_contract_ = FEATURE_CONTRACT
    model.rba_training_provenance_ = meta
    cal_scores = np.asarray(scores_with_model(model, X[cal]))
    # Select only on independent benign calibration rows, never on the test set.
    threshold = float(np.quantile(cal_scores[y[cal] == 0], .99, method="higher"))
    test_scores = np.asarray(scores_with_model(model, X[test]))
    output.mkdir(parents=True, exist_ok=True)
    model_path = output / "iforest_bangkok_v1.pkl"
    joblib.dump(model, model_path)
    report = {"feature_contract": FEATURE_CONTRACT, "timezone": "Asia/Bangkok",
        "runtime": {"python": platform.python_version(), "sklearn": sklearn.__version__,
            "numpy": np.__version__, "joblib": joblib.__version__},
        "validation_scope": "stratified row holdout; not independent-user or real-traffic validation",
        "provenance": meta, "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "split": {"train": len(tr), "calibration": len(cal), "test": len(test)},
        "calibration_threshold": threshold,
        "test": metrics(y[test], test_scores, threshold),
        "test_at_existing_point_0_50": metrics(y[test], test_scores, .50),
        "test_at_existing_monitoring_0_70": metrics(y[test], test_scores, .70),
        "test_roc_auc": float(roc_auc_score(y[test], test_scores)),
        "activation": "staged_only; role percentiles must be rebuilt for this model hash"}
    (output / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(train(args.data, args.output), indent=2))
