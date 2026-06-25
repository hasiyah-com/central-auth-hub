"""Proper train/test protocol บน real-only (ตอบ "generalization" ไม่ใช่ in-sample).

โปรโตคอล one-class + group-by-user (กัน leakage):
  - ATO users -> test ทั้งหมด
  - non-ATO users -> สุ่มแบ่ง 70% train / 30% test
  - TRAIN = normal logins ของ train users เท่านั้น (one-class: fit "ปกติ")
  - TEST  = normal logins ของ test users + login ทั้งหมดของ ATO users
  - threshold ตั้งจาก TRAIN (quantile) แล้ว apply กับ TEST (ไม่ peek test)
  - ทำซ้ำ N split -> mean±std ของ ROC-AUC / PR-AUC / F1 บน TEST

เทียบกับ in-sample (real_only_eval.py) เพื่อดู gap

Run:
    py ml-service/scripts/real_only_split_eval.py
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
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

DATA = Path(__file__).resolve().parents[1] / "data" / "real_only_rba.csv"
N_SPLITS = 10
TRAIN_FRAC = 0.70
FLAG_QUANTILE = 0.99  # threshold = 99th pct ของ train score (≈ flag 1%)

FEATURES = [
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
MODELS = ("IsolationForest", "OneClassSVM", "LocalOutlierFactor")


def _num(v):
    s = str(v).strip().lower()
    return 1.0 if s == "true" else 0.0 if s == "false" else float(s)


def load():
    with open(DATA, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    X = np.array([[_num(r[c]) for c in FEATURES] for r in rows])
    y = np.array([int(r["label"]) for r in rows])
    uid = np.array([r["user_id"] for r in rows])
    return X, y, uid


def fit_score(name, Xtr, Xte, train_contam):
    if name == "IsolationForest":
        m = IsolationForest(
            n_estimators=200, contamination=train_contam, random_state=0
        ).fit(Xtr)
        return -m.score_samples(Xtr), -m.score_samples(Xte)
    if name == "OneClassSVM":
        m = OneClassSVM(nu=0.05, kernel="rbf", gamma="scale").fit(Xtr)
        return -m.score_samples(Xtr), -m.score_samples(Xte)
    m = LocalOutlierFactor(n_neighbors=20, novelty=True).fit(
        Xtr
    )  # novelty -> score unseen
    return -m.score_samples(Xtr), -m.score_samples(Xte)


def main():
    if not DATA.exists():
        print(f"❌ ไม่พบ {DATA}")
        return
    X, y, uid = load()
    # users
    user_has_ato = defaultdict(int)
    for u, lab in zip(uid, y):
        user_has_ato[u] |= lab
    ato_users = [u for u, a in user_has_ato.items() if a == 1]
    normal_users = [u for u, a in user_has_ato.items() if a == 0]
    print(
        f"real-only: {len(y):,} rows | attack {int(y.sum())} | "
        f"users: ATO={len(ato_users)} normal={len(normal_users)}"
    )
    print(
        f"protocol: one-class, group-by-user, {N_SPLITS} splits ({int(TRAIN_FRAC*100)}% train users)\n"
    )

    res = {m: {"roc": [], "pr": [], "f1": [], "prec": [], "rec": []} for m in MODELS}
    rng = np.random.default_rng(42)
    ato_set = set(ato_users)
    for s in range(N_SPLITS):
        nu = normal_users.copy()
        rng.shuffle(nu)
        k = int(len(nu) * TRAIN_FRAC)
        train_users = set(nu[:k])
        test_users = set(nu[k:]) | ato_set

        tr_mask = np.array([u in train_users for u in uid]) & (
            y == 0
        )  # train = normal only
        te_mask = np.array([u in test_users for u in uid])
        Xtr, Xte, yte = X[tr_mask], X[te_mask], y[te_mask]
        if yte.sum() == 0 or len(Xtr) < 50:
            continue

        sc = StandardScaler().fit(Xtr)
        Xtr_s, Xte_s = sc.transform(Xtr), sc.transform(Xte)
        contam = 0.01
        for name in MODELS:
            s_tr, s_te = fit_score(name, Xtr_s, Xte_s, contam)
            thr = np.quantile(s_tr, FLAG_QUANTILE)  # threshold จาก train เท่านั้น
            pred = (s_te >= thr).astype(int)
            res[name]["roc"].append(roc_auc_score(yte, s_te))
            res[name]["pr"].append(average_precision_score(yte, s_te))
            res[name]["f1"].append(f1_score(yte, pred, zero_division=0))
            res[name]["prec"].append(precision_score(yte, pred, zero_division=0))
            res[name]["rec"].append(recall_score(yte, pred, zero_division=0))

    def ms(v):
        return f"{statistics.mean(v):.3f}±{statistics.pstdev(v):.3f}"

    print(
        f"{'Model':<20}{'ROC-AUC':>14}{'PR-AUC':>14}{'F1@1%':>14}{'Prec':>12}{'Recall':>12}"
    )
    print("-" * 86)
    for name in MODELS:
        r = res[name]
        print(
            f"{name:<20}{ms(r['roc']):>14}{ms(r['pr']):>14}{ms(r['f1']):>14}{ms(r['prec']):>12}{ms(r['rec']):>12}"
        )

    print(
        "\nหมายเหตุ: TEST = normal (held-out users) + ATO จริงทั้งหมด; threshold ตั้งจาก TRAIN"
    )
    print("เทียบ in-sample (real_only_eval.py): IForest ROC 0.872 / PR 0.079")


if __name__ == "__main__":
    main()
