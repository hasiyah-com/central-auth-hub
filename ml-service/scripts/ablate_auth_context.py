"""Paired ablation on one registered dataset/split. Offline metrics, no activation."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import platform
from pathlib import Path
import time

import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, roc_auc_score, roc_curve

from app.features import FEATURE_NAMES
from scripts.compare_auth_context import read_dataset, split_users, CONTEXT_NAMES
from point_scoring import scores_with_model

GROUPS = {"recovery_reset": CONTEXT_NAMES[:4], "auth_method": CONTEXT_NAMES[4:9],
          "aaguid": CONTEXT_NAMES[9:12], "language": CONTEXT_NAMES[12:15]}


def rates(y, flagged):
    return {"normal": int(sum(y == 0)), "attack": int(sum(y == 1)),
        "fpr": float(flagged[y == 0].mean()) if np.any(y == 0) else None,
        "recall": float(flagged[y == 1].mean()) if np.any(y == 1) else None}


def roc_recall(y, scores, target):
    fpr, tpr, _ = roc_curve(y, scores)
    return float(max(tpr[fpr <= target]))


def run(path, output, individual=True):
    rows, X, y, meta = read_dataset(path)
    seed = meta.get("seed", 42)
    train, cal, test = split_users(rows, seed=seed)
    if sum(y[train] == 0) < 100 or sum(y[cal] == 0) < 100 or set(y[test]) != {0, 1}:
        raise ValueError("insufficient normal train/calibration or mixed test labels")
    names = FEATURE_NAMES + CONTEXT_NAMES
    if X.shape[1] != len(names):
        raise ValueError("ablation requires complete v2 snapshots; do not impute old v1 features")
    configs = [("baseline_23", FEATURE_NAMES)]
    configs += [("plus_"+group, FEATURE_NAMES+features) for group, features in GROUPS.items()]
    configs += [("all_38", names), ("new_only_15", CONTEXT_NAMES)]
    if individual:
        configs += [("single_"+feature, FEATURE_NAMES+[feature]) for feature in CONTEXT_NAMES]
    test_rows = [rows[i] for i in test]
    allow = np.asarray([r.get("l1_l2_decision") == "allow" for r in test_rows])
    report = {"scope": "offline ablation; no authority or production changes", "dataset": meta,
        "runtime": {"python": platform.python_version(), "sklearn": sklearn.__version__, "numpy": np.__version__},
        "seed": seed, "split": {key: {"rows": len(indices), "users": len({rows[i]["subject"] for i in indices})}
            for key, indices in [("train", train), ("calibration", cal), ("test", test)]},
        "split_sha256": hashlib.sha256(json.dumps([s.tolist() for s in [train, cal, test]]).encode()).hexdigest(),
        "targets": {"warn_fpr": .01, "hypothetical_challenge_fpr": .001}, "results": {}}
    for label, features in configs:
        cols = [names.index(n) for n in features]
        model = IsolationForest(n_estimators=100, contamination=.02, max_samples=256,
                                random_state=seed, n_jobs=1)
        model.fit(X[train][y[train] == 0][:, cols])
        normal_cal = np.asarray(scores_with_model(model, X[cal][:, cols]))[y[cal] == 0]
        warn = float(np.quantile(normal_cal, .99, method="higher"))
        challenge = float(np.quantile(normal_cal, .999, method="higher"))
        scores = np.asarray(scores_with_model(model, X[test][:, cols]))
        flagged = scores > warn
        latency = []
        for i in range(min(100, len(test))):
            at = time.perf_counter()
            scores_with_model(model, X[test[i:i+1]][:, cols])
            latency.append((time.perf_counter()-at)*1000)
        families = {family: rates(y[test][mask], flagged[mask]) for family in
                    sorted({r.get("attack_family", "unknown") for r in test_rows})
                    for mask in [np.asarray([r.get("attack_family", "unknown") == family for r in test_rows])]}
        history = {group: rates(y[test][mask], flagged[mask]) for group in
                   sorted({r.get("history_group", "unknown") for r in test_rows})
                   for mask in [np.asarray([r.get("history_group", "unknown") == group for r in test_rows])]}
        result = {"features": features, "feature_count": len(features),
            "warn_threshold": warn, "hypothetical_challenge_threshold": challenge,
            "warn": rates(y[test], flagged), "hypothetical_challenge": rates(y[test], scores > challenge),
            "roc_auc": float(roc_auc_score(y[test], scores)),
            "pr_auc_average_precision": float(average_precision_score(y[test], scores)),
            "roc_recall_at_test_fpr_le_1pct": roc_recall(y[test], scores, .01),
            "roc_recall_at_test_fpr_le_0_1pct": roc_recall(y[test], scores, .001),
            "additional_attacks_after_l1_l2_allow": int(sum(flagged & allow & (y[test] == 1))),
            "attacks_l1_l2_allow": int(sum(allow & (y[test] == 1))),
            "conditional_allow": rates(y[test][allow], flagged[allow]),
            "by_family": families, "by_history": history,
            "single_row_model_p95_ms": float(np.percentile(latency, 95)),
            "latency_scope": "model-only, warm local CPU; excludes extraction, DB, Redis, HTTP",
            "threshold_note": "normal calibration only; achieved test FPR may differ due ties/sample variation",
            "roc_note": "test ROC points are descriptive, never used as deployed thresholds"}
        report["results"][label] = result
        print(label, json.dumps({"warn": result["warn"], "PR_AP": result["pr_auc_average_precision"]}))
    report["l1_l2_feature_only"] = {"warn_or_higher": rates(y[test], ~allow),
        "challenge_or_block": rates(y[test], np.asarray([r.get("l1_l2_decision") in {"challenge", "block"} for r in test_rows])),
        "scope": "actual current rule/behavior/aggregation code, simulated profile; DB-only checks not evaluated"}
    output.mkdir(parents=True, exist_ok=True)
    (output/"ablation.json").write_text(json.dumps(report, indent=2))
    with (output/"ablation.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["model", "features", "warn_fpr", "warn_recall", "challenge_fpr_simulated",
            "challenge_recall_simulated", "PR_AP", "ROC_AUC", "ROC_recall_FPR_le_1pct",
            "additional_attacks", "model_only_p95_ms"])
        for label, r in report["results"].items():
            writer.writerow([label, r["feature_count"], r["warn"]["fpr"], r["warn"]["recall"],
                r["hypothetical_challenge"]["fpr"], r["hypothetical_challenge"]["recall"],
                r["pr_auc_average_precision"], r["roc_auc"], r["roc_recall_at_test_fpr_le_1pct"],
                r["additional_attacks_after_l1_l2_allow"], r["single_row_model_p95_ms"]])
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--groups-only", action="store_true")
    args = parser.parse_args()
    run(args.data, args.output, not args.groups_only)
