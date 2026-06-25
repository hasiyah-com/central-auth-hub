"""Robustness study — เสริมความหนักแน่นก่อนอ้างในเล่ม (ต่อจาก evaluate_models.py).

ตอบ 3 ข้อ:
  1) Multi-seed: subsample 80% × N รอบ -> mean±std + 95% CI ของ PR-AUC / ROC-AUC
     (threshold-free -> ไม่ขึ้นกับ contamination)
  2) Wilcoxon signed-rank: OCSVM vs IForest (PR-AUC ข้าม seed) -> ต่างกันจริงหรือ noise?
  3) Operating-point sweep: flag-rate 0.5%..5% -> precision/recall/F1 trade-off
     (threshold คือ quantile ของ anomaly score ดิบ — แยกจากการเทรน)

โฟกัสที่ Experiment C (23 features = ชุด deployment).

Run:
    py ml-service/scripts/robustness_eval.py
ต้องมี: numpy, scikit-learn, scipy
"""

import csv
import statistics
from pathlib import Path

import numpy as np
from scipy.stats import wilcoxon
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

DATA = Path(__file__).resolve().parents[1] / "data" / "benchmark_rba.csv"
N_SEEDS = 20
SUBSAMPLE = 0.8
FLAG_RATES = [0.005, 0.01, 0.0138, 0.02, 0.05]

FEATURES_C = [
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
    "concurrent_session_count",
    "active_subsystem_count",
    "weekday_usage_score",
    "scope_sensitivity_score",
    "permission_change_age",
    "confirmed_incident_count",
    "passkey_count",
    "passkey_age_days",
    "new_passkey_recently_added",
    "passkey_last_used_days",
]
MODELS = ("IsolationForest", "OneClassSVM", "LocalOutlierFactor")


def load():
    with open(DATA, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    y = np.array([int(r["label"]) for r in rows])
    X = np.column_stack([np.array([float(r[c]) for r in rows]) for c in FEATURES_C])
    return X, y


def score_model(name, X, contamination):
    Xs = StandardScaler().fit_transform(X)
    if name == "IsolationForest":
        m = IsolationForest(
            n_estimators=200, contamination=contamination, random_state=0
        )
        m.fit(Xs)
        return -m.score_samples(Xs)
    if name == "OneClassSVM":
        m = OneClassSVM(nu=max(contamination, 0.01), kernel="rbf", gamma="scale")
        m.fit(Xs)
        return -m.score_samples(Xs)
    m = LocalOutlierFactor(n_neighbors=20, contamination=contamination)
    m.fit_predict(Xs)
    return -m.negative_outlier_factor_


def ci95(vals):
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return lo, hi


def main():
    if not DATA.exists():
        print(f"❌ ไม่พบ {DATA}")
        return
    X, y = load()
    cont = float(y.mean())
    print(
        f"dataset: {len(y):,} | attack {int(y.sum())} ({cont*100:.2f}%) | features={len(FEATURES_C)} (Exp C)"
    )
    print(
        f"robustness: {N_SEEDS} seeds × subsample {int(SUBSAMPLE*100)}% (stratified)\n"
    )

    # ---- 1) multi-seed PR-AUC / ROC-AUC ----
    pr = {m: [] for m in MODELS}
    roc = {m: [] for m in MODELS}
    for seed in range(N_SEEDS):
        Xs, _, ys, _ = train_test_split(
            X, y, train_size=SUBSAMPLE, random_state=seed, stratify=y
        )
        c = float(ys.mean())
        for name in MODELS:
            s = score_model(name, Xs, c)
            pr[name].append(average_precision_score(ys, s))
            roc[name].append(roc_auc_score(ys, s))

    print("=== 1) Multi-seed (mean ± std [95% CI]) — Experiment C ===")
    print(f"{'Model':<20}{'PR-AUC':>26}{'ROC-AUC':>26}")
    for name in MODELS:
        pm, ps = statistics.mean(pr[name]), statistics.pstdev(pr[name])
        rm, rs = statistics.mean(roc[name]), statistics.pstdev(roc[name])
        pl, ph = ci95(pr[name])
        rl, rh = ci95(roc[name])
        print(
            f"{name:<20}{pm:.3f}±{ps:.3f} [{pl:.3f},{ph:.3f}]   {rm:.3f}±{rs:.3f} [{rl:.3f},{rh:.3f}]"
        )

    # ---- 2) Wilcoxon OCSVM vs IForest ----
    print("\n=== 2) Wilcoxon signed-rank (PR-AUC, OCSVM vs IsolationForest) ===")
    diff = np.array(pr["OneClassSVM"]) - np.array(pr["IsolationForest"])
    stat, p = wilcoxon(pr["OneClassSVM"], pr["IsolationForest"])
    print(f"   mean diff (OCSVM − IForest) = {diff.mean():+.3f}")
    print(
        f"   W={stat:.1f}  p={p:.4f}  -> {'ต่างกันอย่างมีนัยสำคัญ (p<0.05)' if p < 0.05 else 'ต่างกันในขอบเขต noise (p≥0.05)'}"
    )

    # ---- 3) operating-point sweep (full data, threshold = score quantile) ----
    print("\n=== 3) Operating-point sweep (Precision / Recall / F1 @ flag-rate) ===")
    full_scores = {name: score_model(name, X, cont) for name in MODELS}
    for name in MODELS:
        s = full_scores[name]
        print(f"\n  {name}")
        print(f"    {'flag%':>7}{'thr':>9}{'Prec':>8}{'Recall':>8}{'F1':>8}")
        for fr in FLAG_RATES:
            thr = np.quantile(s, 1 - fr)
            pred = (s >= thr).astype(int)
            tp = int(((pred == 1) & (y == 1)).sum())
            fp = int(((pred == 1) & (y == 0)).sum())
            fn = int(((pred == 0) & (y == 1)).sum())
            prec = tp / (tp + fp) if tp + fp else 0.0
            rec = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
            print(f"    {fr*100:>6.2f}%{thr:>9.3f}{prec:>8.3f}{rec:>8.3f}{f1:>8.3f}")


if __name__ == "__main__":
    main()
