"""เปรียบเทียบโมเดล unsupervised บน benchmark_rba.csv (การทดสอบ.md §10–11).

Experiment A (13) / B (19) / C (23 features)  ×  {IsolationForest, OneClassSVM, LOF}
วัดผลด้วย label (ground-truth — ใช้ "วัดผล" เท่านั้น ไม่ป้อนเข้าโมเดล):
  Precision, Recall, F1, ROC-AUC, PR-AUC (PR-AUC = ตัวหลัก เพราะ imbalanced)

Run:
    py ml-service/scripts/evaluate_models.py
ต้องมี: numpy, scikit-learn
"""

import csv
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

DATA = Path(__file__).resolve().parents[1] / "data" / "benchmark_rba.csv"

FEATURES_A = [
    "hour_of_day",
    "day_of_week",
    "hours_from_typical_login_time",
    "is_thailand",
    "is_new_country",
    "country_change_count_30d",
    "is_new_device",
    "is_new_user_agent_family",
    "log_minutes_since_last_login",
    "login_count_24h",
    "failed_logins_24h",
    "is_attack_ip",
    "active_session_count",
]
FEATURES_B = FEATURES_A + [
    "concurrent_session_count",
    "active_subsystem_count",
    "weekday_usage_score",
    "scope_sensitivity_score",
    "permission_change_age",
    "confirmed_incident_count",
]
FEATURES_C = FEATURES_B + [
    "passkey_count",
    "passkey_age_days",
    "new_passkey_recently_added",
    "passkey_last_used_days",
]
EXPERIMENTS = {"A (13)": FEATURES_A, "B (19)": FEATURES_B, "C (23)": FEATURES_C}


def load():
    with open(DATA, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    y = np.array([int(r["label"]) for r in rows])
    cols = {c: np.array([float(r[c]) for r in rows]) for c in FEATURES_C}
    return cols, y


def matrix(cols, names):
    return np.column_stack([cols[n] for n in names])


def anomaly_scores(model_name, X, contamination):
    """คืน continuous anomaly score (สูง=ผิดปกติ) + binary pred."""
    Xs = StandardScaler().fit_transform(X)
    if model_name == "IsolationForest":
        m = IsolationForest(
            n_estimators=200, contamination=contamination, random_state=42
        )
        m.fit(Xs)
        score = -m.score_samples(Xs)  # invert: สูง=ผิดปกติ
        pred = (m.predict(Xs) == -1).astype(int)
    elif model_name == "OneClassSVM":
        m = OneClassSVM(nu=max(contamination, 0.01), kernel="rbf", gamma="scale")
        m.fit(Xs)
        score = -m.score_samples(Xs)
        pred = (m.predict(Xs) == -1).astype(int)
    else:  # LocalOutlierFactor
        m = LocalOutlierFactor(n_neighbors=20, contamination=contamination)
        pred = (m.fit_predict(Xs) == -1).astype(int)
        score = -m.negative_outlier_factor_
    return score, pred


def main():
    if not DATA.exists():
        print(f"❌ ไม่พบ {DATA} — รัน build_benchmark.py ก่อน")
        return
    cols, y = load()
    contamination = float(y.mean())
    print(f"dataset: {len(y):,} rows | attack={y.sum()} ({contamination*100:.2f}%)\n")

    header = f"{'Experiment':<10}{'Model':<18}{'Prec':>7}{'Recall':>8}{'F1':>7}{'ROC-AUC':>9}{'PR-AUC':>8}"
    print(header)
    print("-" * len(header))
    results = []
    for exp, names in EXPERIMENTS.items():
        X = matrix(cols, names)
        for model in ("IsolationForest", "OneClassSVM", "LocalOutlierFactor"):
            score, pred = anomaly_scores(model, X, contamination)
            prec = precision_score(y, pred, zero_division=0)
            rec = recall_score(y, pred, zero_division=0)
            f1 = f1_score(y, pred, zero_division=0)
            roc = roc_auc_score(y, score)
            pr = average_precision_score(y, score)
            results.append((exp, model, prec, rec, f1, roc, pr))
            print(
                f"{exp:<10}{model:<18}{prec:>7.3f}{rec:>8.3f}{f1:>7.3f}{roc:>9.3f}{pr:>8.3f}"
            )
        print()
    return results


if __name__ == "__main__":
    main()
