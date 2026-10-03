"""Offline paired ablation: retrained 23-input baseline versus 32-input candidate.

Both train only on labeled normal rows; users are disjoint across train/cal/test.
Neither model is loaded by production. Require real exported snapshots for results.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import roc_auc_score

from app.features import FEATURE_CONTRACT, FEATURE_NAMES, FEATURE_RANGES
from point_scoring import scores_with_model

CONTEXT_CONTRACT = "l3-auth-context-v1"
CONTEXT_NAMES = ["recovery_observed", "recovery_log1p_hours",
                 "factor_reset_observed", "factor_reset_log1p_hours",
                 "auth_method_known", "auth_phishing_resistant",
                 "prior_auth_observed", "prior_passkey_rate", "auth_method_departure"]


def read_dataset(path):
    meta = json.loads(path.with_suffix(path.suffix + ".meta.json").read_text())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    names = FEATURE_NAMES + CONTEXT_NAMES
    if (meta.get("dataset_sha256") != digest or meta.get("contract") != CONTEXT_CONTRACT
        or meta.get("base_feature_contract") != FEATURE_CONTRACT
        or meta.get("feature_names") != names):
        raise ValueError("dataset checksum/contract/order mismatch")
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows or len({r["session"] for r in rows}) != len(rows):
        raise ValueError("empty dataset or duplicate sessions")
    if any(set(r["features"]) != set(names) or r["label"] not in (0, 1) for r in rows):
        raise ValueError("invalid labels or feature keys")
    X = np.asarray([[r["features"][n] for n in names] for r in rows], dtype=float)
    y = np.asarray([r["label"] for r in rows], dtype=int)
    if not np.isfinite(X).all():
        raise ValueError("nonfinite inputs")
    for i, name in enumerate(names):
        lo, hi = FEATURE_RANGES[name] if name in FEATURE_RANGES else (
            (0, np.log1p(24 * 365)) if name.endswith("log1p_hours") else (0, 1))
        if np.any((X[:, i] < lo) | (X[:, i] > hi)):
            raise ValueError("input out of range: " + name)
    return rows, X, y, meta


def split_users(rows, seed=42):
    users = sorted({r["subject"] for r in rows})
    if len(users) < 15:
        raise ValueError("need at least 15 distinct labeled users for disjoint holdouts")
    np.random.default_rng(seed).shuffle(users)
    a, b = int(.6 * len(users)), int(.8 * len(users))
    groups = [set(users[:a]), set(users[a:b]), set(users[b:])]
    return [np.asarray([i for i, r in enumerate(rows) if r["subject"] in group])
            for group in groups]


def evaluate(y, scores, threshold):
    flagged = scores > threshold
    return {"normal": int((y == 0).sum()), "attack": int((y == 1).sum()),
            "fpr": float(flagged[y == 0].mean()) if np.any(y == 0) else None,
            "recall": float(flagged[y == 1].mean()) if np.any(y == 1) else None,
            "roc_auc": float(roc_auc_score(y, scores)) if set(y) == {0, 1} else None}


def compare(path, output):
    rows, X, y, meta = read_dataset(path)
    train, cal, test = split_users(rows)
    if (sum(y[train] == 0) < 20 or sum(y[cal] == 0) < 20
        or set(y[test]) != {0, 1}):
        raise ValueError("need >=20 train/cal normals and both labels in test; never resplit to improve results")
    output.mkdir(parents=True, exist_ok=True)
    report = {"activation": "offline_only; real-data and role calibration required",
              "dataset": meta, "split": {"train": train.tolist(), "calibration": cal.tolist(),
                                          "test": test.tolist()},
              "scope": "disjoint-user holdout; primary method before step-up; not temporal holdout",
              "results": {}}
    for name, dimensions in [("baseline_23", len(FEATURE_NAMES)), ("candidate_32", X.shape[1])]:
        model = IsolationForest(n_estimators=100, contamination=.02, max_samples=min(256, int(sum(y[train] == 0))),
                                random_state=42, n_jobs=-1)
        model.fit(X[train][y[train] == 0, :dimensions])
        model.rba_feature_contract_ = FEATURE_CONTRACT if dimensions == 23 else CONTEXT_CONTRACT
        model.rba_feature_names_ = (FEATURE_NAMES + CONTEXT_NAMES)[:dimensions]
        model.rba_training_provenance_ = meta
        cal_scores = np.asarray(scores_with_model(model, X[cal, :dimensions]))
        threshold = float(np.quantile(cal_scores[y[cal] == 0], .99, method="higher"))
        scores = np.asarray(scores_with_model(model, X[test, :dimensions]))
        artifact = output / (name + ".candidate.pkl")
        joblib.dump(model, artifact)
        role_results = {}
        for role in ["admin", "staff", "teacher", "student"]:
            cal_role = np.asarray([rows[i].get("user_type") == role for i in cal])
            normal_role = cal_role & (y[cal] == 0)
            test_role = np.asarray([rows[i].get("user_type") == role for i in test])
            if sum(normal_role) < 20:
                role_results[role] = {"status": "abstain", "normal_calibration_rows": int(sum(normal_role))}
                continue
            role_threshold = float(np.quantile(cal_scores[normal_role], .99, method="higher"))
            role_results[role] = {"status": "staged_only", "normal_calibration_rows": int(sum(normal_role)),
                                  "p99_threshold": role_threshold,
                                  "test": evaluate(y[test][test_role], scores[test_role], role_threshold)}
        report["results"][name] = {
            "model_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "threshold_from_normal_calibration_p99": threshold,
            "test": evaluate(y[test], scores, threshold),
            "roles": role_results,
        }
    report["delta_candidate_minus_baseline"] = {
        key: report["results"]["candidate_32"]["test"][key] -
             report["results"]["baseline_23"]["test"][key]
        for key in ["fpr", "recall", "roc_auc"]}
    (output / "comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(compare(args.data, args.output), indent=2))
