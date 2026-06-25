"""ข้อ 1: Proper train/test protocol บน SEMI-SYNTHETIC (apples-to-apples กับ real-only).

โปรโตคอลเดียวกับ real_only_split_eval.py:
  one-class (เทรน normal-only) + group-by-user + threshold จาก train + 10 splits

รัน 2 feature set บน semi-synth เพื่อ "แยกตัวแปร":
  - 12 feat  = เซ็ตเดียวกับ real-only -> เทียบกับ real-only@12 ได้ตรงๆ
               => ต่างกันเพราะ "ความสมจริงของ attack" (synthetic vs ATO จริง)
  - 23 feat  = Experiment C เต็ม
               => 12 vs 23 ต่างกันเพราะ "feature set" (passkey/session ช่วยไหม)

อ้างอิง real-only@12 (proper, จาก real_only_split_eval.py):
  IForest ROC 0.890±0.041 PR 0.427±0.166 | OCSVM ROC 0.839 PR 0.414

Run:
    py ml-service/scripts/proper_split_semisynth.py
"""

import csv
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    recall_score,
    roc_auc_score,
)
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

DATA = Path(__file__).resolve().parents[1] / "data" / "benchmark_rba.csv"
N_SPLITS = 10
TRAIN_FRAC = 0.70
FLAG_QUANTILE = 0.99

FEATURES_12 = [
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
]
FEATURES_23 = FEATURES_12 + [
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


def _num(v):
    s = str(v).strip().lower()
    return 1.0 if s == "true" else 0.0 if s == "false" else float(s)


def load():
    with open(DATA, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    y = np.array([int(r["label"]) for r in rows])
    uid = np.array([r["user_id"] for r in rows])
    cols = {c: np.array([_num(r[c]) for r in rows]) for c in FEATURES_23}
    return cols, y, uid


def fit_score(name, Xtr, Xte):
    if name == "IsolationForest":
        m = IsolationForest(n_estimators=200, contamination=0.01, random_state=0).fit(
            Xtr
        )
        return -m.score_samples(Xtr), -m.score_samples(Xte)
    if name == "OneClassSVM":
        m = OneClassSVM(nu=0.05, kernel="rbf", gamma="scale").fit(Xtr)
        return -m.score_samples(Xtr), -m.score_samples(Xte)
    m = LocalOutlierFactor(n_neighbors=20, novelty=True).fit(Xtr)
    return -m.score_samples(Xtr), -m.score_samples(Xte)


def run(cols, y, uid, names):
    X = np.column_stack([cols[n] for n in names])
    user_ato = defaultdict(int)
    for u, lab in zip(uid, y):
        user_ato[u] |= lab
    ato_users = set(u for u, a in user_ato.items() if a)
    normal_users = [u for u, a in user_ato.items() if not a]

    res = {m: {"roc": [], "pr": [], "f1": [], "rec": []} for m in MODELS}
    rng = np.random.default_rng(42)
    for _ in range(N_SPLITS):
        nu = normal_users.copy()
        rng.shuffle(nu)
        k = int(len(nu) * TRAIN_FRAC)
        train_u = set(nu[:k])
        test_u = set(nu[k:]) | ato_users
        tr = np.array([u in train_u for u in uid]) & (y == 0)
        te = np.array([u in test_u for u in uid])
        Xtr, Xte, yte = X[tr], X[te], y[te]
        if yte.sum() == 0 or len(Xtr) < 50:
            continue
        sc = StandardScaler().fit(Xtr)
        Xtr_s, Xte_s = sc.transform(Xtr), sc.transform(Xte)
        for name in MODELS:
            s_tr, s_te = fit_score(name, Xtr_s, Xte_s)
            thr = np.quantile(s_tr, FLAG_QUANTILE)
            pred = (s_te >= thr).astype(int)
            res[name]["roc"].append(roc_auc_score(yte, s_te))
            res[name]["pr"].append(average_precision_score(yte, s_te))
            res[name]["f1"].append(f1_score(yte, pred, zero_division=0))
            res[name]["rec"].append(recall_score(yte, pred, zero_division=0))
    return res


def ms(v):
    return f"{statistics.mean(v):.3f}±{statistics.pstdev(v):.3f}" if v else "-"


def show(title, res):
    print(f"\n=== {title} ===")
    print(f"{'Model':<20}{'ROC-AUC':>14}{'PR-AUC':>14}{'F1@1%':>14}{'Recall':>12}")
    print("-" * 74)
    for n in MODELS:
        r = res[n]
        print(
            f"{n:<20}{ms(r['roc']):>14}{ms(r['pr']):>14}{ms(r['f1']):>14}{ms(r['rec']):>12}"
        )


def main():
    if not DATA.exists():
        print(f"❌ ไม่พบ {DATA}")
        return
    cols, y, uid = load()
    print(
        f"semi-synth: {len(y):,} rows | attack {int(y.sum())} | "
        f"protocol: one-class, group-by-user, {N_SPLITS} splits"
    )
    show("SEMI-SYNTH @ 12 feat (เทียบ real-only ได้ตรงๆ)", run(cols, y, uid, FEATURES_12))
    show("SEMI-SYNTH @ 23 feat (Experiment C เต็ม)", run(cols, y, uid, FEATURES_23))
    print("\n=== REAL-ONLY @ 12 feat (อ้างอิง จาก real_only_split_eval.py) ===")
    print(
        f"{'IsolationForest':<20}{'0.890±0.041':>14}{'0.427±0.166':>14}{'0.325':>14}{'0.265':>12}"
    )
    print(
        f"{'OneClassSVM':<20}{'0.839±0.028':>14}{'0.414±0.164':>14}{'0.486':>14}{'0.500':>12}"
    )
    print("\nอ่านผล:")
    print("  • semi@12 vs real@12  -> ต่างเพราะ 'ความสมจริงของ attack'")
    print("  • semi@12 vs semi@23  -> ต่างเพราะ 'feature set' (passkey/session ช่วยไหม)")


if __name__ == "__main__":
    main()
